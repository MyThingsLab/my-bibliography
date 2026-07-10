from __future__ import annotations

import json
from pathlib import Path

from mythings.ledger import Ledger

from conftest import (
    FakeRunner,
    ScriptedEngine,
    SpyEngine,
    branch_file,
    empty_fetch,
    fake_fetch,
    make_repo,
)
from mybibliography.bibliography_tool import Bibliography

_RESOLVE_REPLY = json.dumps(
    {
        "chosen_candidate_id": "doi:10.1234/gnn",
        "key": "lovelace2021",
        "rejected": [],
        "confidence": "medium",
    }
)


def _bibliography(
    repo: Path, tmp_path: Path, fake: FakeRunner, **kw
) -> tuple[Bibliography, Ledger]:
    ledger = Ledger(tmp_path / "ledger.jsonl")
    b = Bibliography(
        repo_root=repo,
        repo="owner/name",
        ledger=ledger,
        runner=fake,
        fetch=fake_fetch,
        **kw,
    )
    return b, ledger


def test_add_happy_path_direct_locator_opens_pr_and_comments(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    fake = FakeRunner(body="doi:10.1234/gnn")
    b, ledger = _bibliography(repo, tmp_path, fake, engine=ScriptedEngine(_RESOLVE_REPLY))

    result = b.add(issue=5)

    assert result.outcome == "success"
    assert result.pr == 7
    assert result.key == "lovelace2021"
    assert any(c[:2] == ["pr", "create"] for c in fake.calls)
    assert any(c[:2] == ["issue", "comment"] for c in fake.calls)

    committed_bib = branch_file(repo, "my-bibliography/5", "references.bib")
    assert "@article{lovelace2021," in committed_bib
    committed_json = branch_file(repo, "my-bibliography/5", "references.json")
    assert '"id": "lovelace2021"' in committed_json

    entry = list(ledger)[0]
    assert entry.kind == "bibliography"
    assert entry.outcome == "success"
    assert entry.data["pr"] == 7
    assert entry.data["key"] == "lovelace2021"
    assert entry.data["confidence"] == "medium"


def test_add_happy_path_ambiguous_query_matches_retrieved_fields_not_engine_claims(
    tmp_path: Path,
) -> None:
    repo = make_repo(tmp_path)
    fake = FakeRunner(body='query:"effective java"')
    # The scripted reply smuggles extra bibliographic fields the tool must ignore.
    reply = json.dumps(
        {
            "chosen_candidate_id": "isbn:9780134685991",
            "key": "bloch2018",
            "title": "A HALLUCINATED TITLE",
            "author": "Someone Invented",
            "rejected": [{"candidate_id": "doi:10.1234/gnn", "why": "wrong type"}],
            "confidence": "low",
        }
    )
    b, ledger = _bibliography(repo, tmp_path, fake, engine=ScriptedEngine(reply))

    result = b.add(issue=6)

    assert result.outcome == "success"
    committed_bib = branch_file(repo, "my-bibliography/6", "references.bib")
    assert "@book{bloch2018," in committed_bib
    assert "Effective Java" in committed_bib  # the retrieved title, not the hallucinated one
    assert "HALLUCINATED" not in committed_bib

    entry = [e for e in ledger if e.outcome == "success"][0]
    assert entry.data["rejected"] == [{"candidate_id": "doi:10.1234/gnn", "why": "wrong type"}]


def test_add_no_candidates_skips_engine_and_pr(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    fake = FakeRunner(body="doi:10.9999/missing")
    spy = SpyEngine()
    b, ledger = _bibliography(repo, tmp_path, fake, engine=spy)
    b.fetch = empty_fetch

    result = b.add(issue=5)

    assert result.outcome == "skipped"
    assert spy.calls == []  # engine never called when nothing was retrieved
    assert not any(c[:2] == ["pr", "create"] for c in fake.calls)
    assert any(c[:2] == ["issue", "comment"] for c in fake.calls)
    entry = list(ledger)[0]
    assert entry.outcome == "skipped"
    assert "no metadata found" in entry.detail


def test_add_already_cataloged_skips_engine_and_pr(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    (repo / "references.json").write_text(
        json.dumps([{"id": "lovelace2021", "DOI": "10.1234/gnn"}]), encoding="utf-8"
    )
    fake = FakeRunner(body="doi:10.1234/gnn")
    spy = SpyEngine()
    b, ledger = _bibliography(repo, tmp_path, fake, engine=spy)

    result = b.add(issue=5)

    assert result.outcome == "skipped"
    assert result.key == "lovelace2021"
    assert spy.calls == []
    assert not any(c[:2] == ["pr", "create"] for c in fake.calls)
    assert any(c[:2] == ["issue", "comment"] for c in fake.calls)
    entry = list(ledger)[0]
    assert "already in bibliography" in entry.detail


def test_add_no_locator_in_body_skips(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    fake = FakeRunner(body="just some prose, no locator")
    spy = SpyEngine()
    b, ledger = _bibliography(repo, tmp_path, fake, engine=spy)

    result = b.add(issue=5)

    assert result.outcome == "skipped"
    assert spy.calls == []
    assert list(ledger)[0].outcome == "skipped"


def test_add_no_pr_and_no_comment(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    fake = FakeRunner(body="doi:10.1234/gnn")
    b, _ = _bibliography(repo, tmp_path, fake, engine=ScriptedEngine(_RESOLVE_REPLY))

    result = b.add(issue=5, no_pr=True, no_comment=True)

    assert result.outcome == "success"
    assert result.pr is None
    assert not any(c[:2] == ["pr", "create"] for c in fake.calls)
    assert not any(c[:2] == ["issue", "comment"] for c in fake.calls)


def test_add_reuses_existing_pr(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    fake = FakeRunner(
        body="doi:10.1234/gnn",
        existing_pr={"number": 42, "url": "https://github.com/owner/name/pull/42"},
    )
    b, _ = _bibliography(repo, tmp_path, fake, engine=ScriptedEngine(_RESOLVE_REPLY))

    result = b.add(issue=5, no_comment=True)

    assert result.pr == 42
    assert not any(c[:2] == ["pr", "create"] for c in fake.calls)


def test_noop_engine_single_candidate_degrade_end_to_end(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    fake = FakeRunner(body="doi:10.1234/gnn")
    b, ledger = _bibliography(repo, tmp_path, fake)  # default engine: NoopEngine

    result = b.add(issue=5)

    assert result.outcome == "success"
    entry = [e for e in ledger if e.outcome == "success"][0]
    assert entry.data["confidence"] == "high"
    assert entry.data["key"] == "lovelace2021"


def test_noop_engine_multi_candidate_degrade_end_to_end(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    fake = FakeRunner(body='query:"effective java"')
    b, ledger = _bibliography(repo, tmp_path, fake)  # default engine: NoopEngine

    result = b.add(issue=5)

    assert result.outcome == "success"
    entry = [e for e in ledger if e.outcome == "success"][0]
    assert entry.data["confidence"] == "low"
    assert len(entry.data["rejected"]) >= 1
