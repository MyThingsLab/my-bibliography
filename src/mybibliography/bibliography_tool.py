from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path

from mythings.engine import Engine, NoopEngine
from mythings.github import GitHubError, PullRequest, Runner, _gh, _pr_number
from mythings.isolation import Workspace, in_github_actions
from mythings.ledger import Ledger
from mythings.policy import ALLOW, Action, Decision, Policy, PolicyResult

from mybibliography.bibliography import (
    BIB_FILENAME,
    CSL_FILENAME,
    Entry,
    append_entry,
    find_existing_key,
    render_bibtex,
)
from mybibliography.resolve import Resolution, UnknownCandidateError, resolve
from mybibliography.retrieval import Fetcher, Locator, _http, parse_locator, retrieve

LABEL = "my-bibliography"


class PolicyDenied(RuntimeError):
    pass


class _AllowAll:
    # Default Policy: this tool's two side effects (a committed bibliography
    # PR, an issue comment) are non-destructive and never merge on their own.
    def evaluate(self, action: Action) -> PolicyResult:
        return ALLOW


@dataclass(frozen=True)
class Result:
    outcome: str  # success | skipped | failure
    issue: int | None
    pr: int | None
    detail: str
    key: str | None = None


@dataclass(frozen=True)
class _Issue:
    number: int
    title: str
    body: str


def _git(repo: Path, argv: list[str]) -> None:
    proc = subprocess.run(["git", "-C", str(repo), *argv], capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"git {' '.join(argv)} failed: {proc.stderr.strip()}")


class Bibliography:
    def __init__(
        self,
        *,
        repo_root: str | Path = ".",
        repo: str | None = None,
        ledger: Ledger,
        base: str = "main",
        engine: Engine | None = None,
        policy: Policy | None = None,
        runner: Runner = _gh,
        fetch: Fetcher = _http,
        top: int = 5,
    ) -> None:
        self.repo_root = Path(repo_root)
        self.repo = repo
        self.ledger = ledger
        self.base = base
        self.engine: Engine = engine or NoopEngine()
        self.policy: Policy = policy or _AllowAll()
        self.runner = runner
        self.fetch = fetch
        self.top = top

    # ---- add ---------------------------------------------------------

    def add(
        self,
        issue: int,
        *,
        locator: str | None = None,
        no_pr: bool = False,
        no_comment: bool = False,
    ) -> Result:
        try:
            ref_issue = self._fetch_issue(issue)
        except GitHubError as err:
            return self._fail(issue, f"could not read issue #{issue}: {err}")

        parsed = self._parse_locator(locator, ref_issue.body)
        if parsed is None:
            detail = "no locator (doi:/arxiv:/isbn:/query:) found in issue body"
            url = None if no_comment else self._comment(issue, f"_{detail}_")
            self._record("skipped", issue, None, None, detail, comment_url=url)
            return self._skip(issue, detail)

        candidates = retrieve(parsed, fetch=self.fetch, top=self.top)
        if not candidates:
            detail = f"no metadata found for `{parsed.kind}:{parsed.value}`"
            url = None if no_comment else self._comment(issue, detail)
            self._record(
                "skipped", issue, None, None, detail, comment_url=url, locator=parsed.value
            )
            return self._skip(issue, detail)

        existing_key = find_existing_key(self.repo_root / CSL_FILENAME, candidates)
        if existing_key is not None:
            detail = f"already in bibliography as `{existing_key}`"
            url = None if no_comment else self._comment(issue, detail)
            self._record(
                "skipped",
                issue,
                None,
                existing_key,
                detail,
                comment_url=url,
                locator=parsed.value,
                candidates=len(candidates),
            )
            return self._skip(issue, detail, key=existing_key)

        try:
            resolution = resolve(self.engine, parsed, candidates, ref_issue=issue)
        except UnknownCandidateError as err:
            return self._fail(issue, str(err))

        entry = Entry(key=resolution.key, candidate=resolution.candidate)
        pr = None
        if not no_pr:
            try:
                pr = self._open_pr_with_entry(issue, entry)
            except PolicyDenied as denied:
                return self._fail(issue, str(denied))

        bibtex = render_bibtex(entry)
        comment_body = self._render_comment(bibtex, resolution)
        url = None if no_comment else self._comment(issue, comment_body)

        detail = f"entry for `{parsed.value}` ({len(candidates)} candidates)"
        self._record(
            "success",
            issue,
            pr.number if pr else None,
            entry.key,
            detail,
            comment_url=url,
            locator=parsed.value,
            candidates=len(candidates),
            chosen_candidate_id=resolution.candidate.candidate_id,
            entry=bibtex,
            rejected=[{"candidate_id": r.candidate_id, "why": r.why} for r in resolution.rejected],
            confidence=resolution.confidence,
            bib_path=BIB_FILENAME,
        )
        return Result(
            outcome="success",
            issue=issue,
            pr=pr.number if pr else None,
            detail=detail,
            key=entry.key,
        )

    def _parse_locator(self, locator: str | None, body: str) -> Locator | None:
        if locator:
            return parse_locator(locator)
        return parse_locator(body)

    # ---- github / git helpers -----------------------------------------

    def _fetch_issue(self, number: int) -> _Issue:
        argv = ["issue", "view", str(number), "--json", "number,title,body"]
        if self.repo:
            argv += ["--repo", self.repo]
        obj = json.loads(self.runner(argv))
        return _Issue(number=obj["number"], title=obj["title"], body=obj.get("body") or "")

    def _open_pr_with_entry(self, issue: int, entry: Entry) -> PullRequest:
        branch = f"{LABEL}/{issue}"
        existing = self._existing_pr(branch)
        with Workspace(self.repo_root, self.base) as tree:
            self._git_run(tree, ["checkout", "-B", branch])
            append_entry(tree / BIB_FILENAME, tree / CSL_FILENAME, entry)
            self._git_run(tree, ["add", BIB_FILENAME, CSL_FILENAME])
            self._git_run(tree, ["commit", "-m", f"bibliography: add {entry.key}"])
            self._git_run(tree, ["push", "-u", "origin", branch])
        if existing is not None:
            return existing
        self._guard(f"gh pr create --head {branch} --base {self.base}")
        argv = [
            "pr",
            "create",
            "--title",
            f"bibliography: add {entry.key}",
            "--body",
            f"Adds `{entry.key}` to the bibliography.\n\nCloses #{issue}.",
            "--base",
            self.base,
            "--head",
            branch,
        ]
        if self.repo:
            argv += ["--repo", self.repo]
        url = self.runner(argv).strip().splitlines()[-1]
        return PullRequest(number=_pr_number(url), url=url)

    def _existing_pr(self, branch: str) -> PullRequest | None:
        argv = ["pr", "list", "--head", branch, "--state", "open", "--json", "number,url"]
        if self.repo:
            argv += ["--repo", self.repo]
        rows = json.loads(self.runner(argv))
        if not rows:
            return None
        row = rows[0]
        return PullRequest(number=row.get("number") or _pr_number(row["url"]), url=row["url"])

    def _comment(self, issue: int, body: str) -> str | None:
        if self.repo is None:
            return None
        argv = ["issue", "comment", str(issue), "--repo", self.repo, "--body", body]
        action = Action(kind="bash", payload={"command": f"gh issue comment {issue}"})
        if self.policy.evaluate(action).under(unattended=in_github_actions()) is not Decision.ALLOW:
            return None
        return self.runner(argv).strip() or None

    def _git_run(self, tree: Path, argv: list[str]) -> None:
        self._guard("git " + " ".join(argv))
        _git(tree, argv)

    def _guard(self, command: str) -> None:
        result = self.policy.evaluate(Action(kind="bash", payload={"command": command}))
        if result.under(unattended=in_github_actions()) is not Decision.ALLOW:
            raise PolicyDenied(f"policy blocked: {command} ({result.reason or result.decision})")

    # ---- rendering / ledger / results ----------------------------------

    def _render_comment(self, bibtex: str, resolution: Resolution) -> str:
        lines = [
            "```bibtex",
            bibtex.rstrip(),
            "```",
            "",
            f"Confidence: **{resolution.confidence}**",
        ]
        if resolution.rejected:
            lines.append("")
            lines.append("Rejected candidates:")
            for r in resolution.rejected:
                lines.append(f"- `{r.candidate_id}`: {r.why}")
        return "\n".join(lines)

    def _record(
        self,
        outcome: str,
        issue: int,
        pr: int | None,
        key: str | None,
        detail: str,
        *,
        comment_url: str | None,
        **data,
    ) -> None:
        self.ledger.record(
            tool="mybibliography",
            kind="bibliography",
            outcome=outcome,
            detail=detail,
            issue=issue,
            pr=pr,
            key=key,
            comment_url=comment_url,
            **data,
        )

    def _skip(self, issue: int, detail: str, *, key: str | None = None) -> Result:
        return Result(outcome="skipped", issue=issue, pr=None, detail=detail, key=key)

    def _fail(self, issue: int, detail: str) -> Result:
        self.ledger.record(
            tool="mybibliography",
            kind="bibliography",
            outcome="failure",
            detail=detail,
            issue=issue,
        )
        return Result(outcome="failure", issue=issue, pr=None, detail=detail)
