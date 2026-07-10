from __future__ import annotations

import json

import pytest
from mythings.engine import NoopEngine

from conftest import ScriptedEngine
from mybibliography.resolve import UnknownCandidateError, resolve
from mybibliography.retrieval import Candidate, Locator

_C1 = Candidate(
    candidate_id="doi:10.1/a",
    type="article",
    title="Paper A",
    authors=["Ada Lovelace"],
    year=2021,
    venue="Journal A",
    doi="10.1/a",
    isbn="",
    url="https://doi.org/10.1/a",
)
_C2 = Candidate(
    candidate_id="doi:10.1/b",
    type="article",
    title="Paper B",
    authors=["Alan Turing"],
    year=2019,
    venue="Journal B",
    doi="10.1/b",
    isbn="",
    url="https://doi.org/10.1/b",
)


def test_resolve_parses_engine_json() -> None:
    reply = json.dumps(
        {
            "chosen_candidate_id": "doi:10.1/a",
            "key": "lovelace2021",
            "rejected": [{"candidate_id": "doi:10.1/b", "why": "less relevant"}],
            "confidence": "medium",
        }
    )
    resolution = resolve(
        ScriptedEngine(reply), Locator("query", "paper a"), [_C1, _C2], ref_issue=1
    )
    assert resolution.candidate.candidate_id == "doi:10.1/a"
    assert resolution.key == "lovelace2021"
    assert resolution.confidence == "medium"
    assert [r.candidate_id for r in resolution.rejected] == ["doi:10.1/b"]


def test_resolve_copies_fields_from_retrieved_candidate_not_engine_reply() -> None:
    # The field-integrity invariant: even if the Engine reply smuggled extra
    # bibliographic fields, the tool must never surface them -- only the
    # retrieved candidate's own fields end up on the Resolution.
    reply = json.dumps(
        {
            "chosen_candidate_id": "doi:10.1/a",
            "key": "lovelace2021",
            "title": "A HALLUCINATED TITLE",
            "authors": ["Someone Invented"],
            "year": 1999,
            "doi": "10.9999/fake",
            "rejected": [],
            "confidence": "high",
        }
    )
    resolution = resolve(
        ScriptedEngine(reply), Locator("doi", "10.1/a"), [_C1], ref_issue=1
    )
    assert resolution.candidate.title == "Paper A"
    assert resolution.candidate.authors == ["Ada Lovelace"]
    assert resolution.candidate.year == 2021
    assert resolution.candidate.doi == "10.1/a"


def test_resolve_tolerates_preamble_before_json() -> None:
    reply = (
        "Sure, here is my answer:\n\n"
        + json.dumps({"chosen_candidate_id": "doi:10.1/a", "key": "k", "confidence": "high"})
        + "\nLet me know if you need more."
    )
    resolution = resolve(ScriptedEngine(reply), Locator("doi", "10.1/a"), [_C1], ref_issue=1)
    assert resolution.candidate.candidate_id == "doi:10.1/a"


def test_resolve_tolerates_code_fence() -> None:
    reply = (
        "```json\n"
        + json.dumps({"chosen_candidate_id": "doi:10.1/a", "key": "k", "confidence": "high"})
        + "\n```"
    )
    resolution = resolve(ScriptedEngine(reply), Locator("doi", "10.1/a"), [_C1], ref_issue=1)
    assert resolution.candidate.candidate_id == "doi:10.1/a"


def test_resolve_raises_on_unlisted_candidate_id() -> None:
    reply = json.dumps({"chosen_candidate_id": "doi:99.9/nope", "key": "k", "confidence": "high"})
    with pytest.raises(UnknownCandidateError):
        resolve(ScriptedEngine(reply), Locator("doi", "10.1/a"), [_C1], ref_issue=1)


def test_resolve_unparseable_reply_degrades() -> None:
    resolution = resolve(
        ScriptedEngine("not json at all"), Locator("doi", "10.1/a"), [_C1], ref_issue=1
    )
    assert resolution.candidate.candidate_id == "doi:10.1/a"
    assert resolution.confidence == "high"


def test_noop_engine_single_candidate_auto_chooses() -> None:
    resolution = resolve(NoopEngine(), Locator("doi", "10.1/a"), [_C1], ref_issue=1)
    assert resolution.candidate.candidate_id == "doi:10.1/a"
    assert resolution.confidence == "high"
    assert resolution.key == "lovelace2021"
    assert resolution.rejected == []


def test_noop_engine_multi_candidate_chooses_top_scored() -> None:
    resolution = resolve(
        NoopEngine(), Locator("query", "paper a lovelace"), [_C1, _C2], ref_issue=1
    )
    assert resolution.candidate.candidate_id == "doi:10.1/a"  # matches more query terms
    assert resolution.confidence == "low"
    assert len(resolution.rejected) == 1
    assert resolution.rejected[0].why == "not the top-scored match"


def test_deterministic_key_collision_suffix() -> None:
    from mybibliography.resolve import _deterministic_key

    taken = {"lovelace2021"}
    assert _deterministic_key(_C1, taken) == "lovelace2021a"
