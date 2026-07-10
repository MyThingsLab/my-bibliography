from __future__ import annotations

import argparse
from pathlib import Path

from mythings.engine import ClaudeCLIEngine, Engine, NoopEngine
from mythings.ledger import Ledger

from mybibliography.bibliography_tool import Bibliography, Result


def build_engine(name: str, *, model: str | None = None) -> Engine:
    if name == "claude-cli":
        return ClaudeCLIEngine(model=model)
    return NoopEngine()


def _render(result: Result) -> str:
    line = f"{result.outcome}: {result.detail}"
    if result.pr is not None:
        line += f" — PR #{result.pr}"
    if result.key:
        line += f" [{result.key}]"
    return line


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="mybibliography",
        description="Resolve a reference-request issue to a cataloged bibliography entry.",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    add = sub.add_parser(
        "add", help="resolve one reference-request issue into a bibliography entry"
    )
    add.add_argument("--issue", type=int, required=True, help="the reference-request issue")
    add.add_argument(
        "--locator",
        help='override the issue body, e.g. "doi:10.xxxx", "arxiv:xxxx", '
        '"isbn:xxxx", or \'query:"..."\'',
    )
    add.add_argument("--top", type=int, default=5, help="max candidates to shortlist (default: 5)")
    add.add_argument("--repo", help="GitHub slug owner/name (defaults to the local remote)")
    add.add_argument("--repo-root", type=Path, default=Path.cwd(), help="local git repo")
    add.add_argument("--base", default="main", help="base branch for the PR")
    add.add_argument("--ledger", type=Path, default=Path(".mythings/ledger.jsonl"))
    add.add_argument("--no-pr", action="store_true", help="skip the committed bibliography PR")
    add.add_argument("--no-comment", action="store_true", help="skip the issue comment")
    add.add_argument(
        "--engine",
        choices=("noop", "claude-cli"),
        default="noop",
        help="Engine backend for candidate resolution (default: noop — deterministic degrade)",
    )
    add.add_argument("--engine-model", help="model for --engine claude-cli")

    args = parser.parse_args(argv)
    bibliography = Bibliography(
        repo_root=args.repo_root,
        repo=args.repo,
        ledger=Ledger(args.ledger),
        base=args.base,
        engine=build_engine(args.engine, model=args.engine_model),
        top=args.top,
    )
    result = bibliography.add(
        args.issue, locator=args.locator, no_pr=args.no_pr, no_comment=args.no_comment
    )
    print(_render(result))
    return 1 if result.outcome == "failure" else 0


if __name__ == "__main__":
    raise SystemExit(main())
