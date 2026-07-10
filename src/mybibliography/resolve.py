from __future__ import annotations

import json
import re
from dataclasses import dataclass

from mythings.engine import Engine, EngineRequest, NoopEngine

from mybibliography.retrieval import Candidate, Locator, query_terms, tokenize

_SYSTEM = (
    "You resolve a bibliography reference request to exactly one canonical "
    "candidate from a given shortlist, and invent a short citation key for "
    "it. You may ONLY choose a candidate_id that appears in the shortlist -- "
    "never invent a candidate, a title, an author, a year, a DOI, or an "
    "ISBN. Reply with a single JSON object and nothing else."
)


class UnknownCandidateError(RuntimeError):
    pass


@dataclass(frozen=True)
class Rejection:
    candidate_id: str
    why: str


@dataclass(frozen=True)
class Resolution:
    candidate: Candidate
    key: str
    rejected: list[Rejection]
    confidence: str  # "low" | "medium" | "high"


def _parse_json_object(text: str) -> dict | None:
    # Tolerant parsing: models sometimes wrap the JSON in a ```fence``` or a
    # sentence of preamble/trailing commentary despite the "nothing else"
    # instruction -- same defensive posture as MyResearcher's synthesis.py.
    text = text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        lines = lines[1:-1] if lines and lines[-1].strip() == "```" else lines[1:]
        text = "\n".join(lines).strip()
    try:
        obj = json.loads(text)
        return obj if isinstance(obj, dict) else None
    except (json.JSONDecodeError, ValueError):
        pass
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None
    try:
        obj = json.loads(text[start : end + 1])
    except (json.JSONDecodeError, ValueError):
        return None
    return obj if isinstance(obj, dict) else None


_SURNAME_RE = re.compile(r"[^a-z]")


def _surname(author: str) -> str:
    parts = author.strip().split()
    surname = parts[-1] if parts else "anon"
    return _SURNAME_RE.sub("", surname.lower()) or "anon"


def _deterministic_key(candidate: Candidate, taken: set[str]) -> str:
    surname = _surname(candidate.authors[0]) if candidate.authors else "anon"
    year = str(candidate.year) if candidate.year else "nd"
    base = f"{surname}{year}"
    if base not in taken:
        return base
    for suffix in "abcdefghijklmnopqrstuvwxyz":
        key = f"{base}{suffix}"
        if key not in taken:
            return key
    raise RuntimeError(f"exhausted key suffixes for {base}")


def _prompt(locator: Locator, candidates: list[Candidate]) -> str:
    lines = [f"Reference request locator: {locator.kind}:{locator.value}", "", "Candidates:"]
    for c in candidates:
        authors = ", ".join(c.authors) or "(no authors listed)"
        year = str(c.year) if c.year else "n.d."
        lines.append(
            f"- [{c.candidate_id}] ({c.type}) {c.title!r} by {authors} ({year})"
            f" doi={c.doi or '-'} isbn={c.isbn or '-'} venue={c.venue or '-'}"
        )
    lines.append(
        "\nReturn JSON with keys: "
        '"chosen_candidate_id" (must be one of the candidate_ids above), '
        '"key" (a short citation key you invent, e.g. lastname+year), '
        '"rejected" (array of {"candidate_id","why"} for every other candidate), '
        '"confidence" ("low"|"medium"|"high").'
    )
    return "\n".join(lines)


def _score(candidate: Candidate, query_tokens: set[str]) -> tuple[int, str]:
    haystack = set(tokenize(candidate.title))
    for a in candidate.authors:
        haystack |= set(tokenize(a))
    return (len(query_tokens & haystack), candidate.candidate_id)


def _degrade(locator: Locator, candidates: list[Candidate]) -> Resolution:
    if len(candidates) == 1:
        chosen = candidates[0]
        key = _deterministic_key(chosen, taken=set())
        return Resolution(candidate=chosen, key=key, rejected=[], confidence="high")

    query_tokens = set(query_terms(locator.value))
    ranked = sorted(candidates, key=lambda c: _score(c, query_tokens), reverse=True)
    chosen = ranked[0]
    key = _deterministic_key(chosen, taken=set())
    rejected = [
        Rejection(candidate_id=c.candidate_id, why="not the top-scored match")
        for c in ranked[1:]
    ]
    return Resolution(candidate=chosen, key=key, rejected=rejected, confidence="low")


def resolve(
    engine: Engine, locator: Locator, candidates: list[Candidate], *, ref_issue: int
) -> Resolution:
    if isinstance(engine, NoopEngine):
        return _degrade(locator, candidates)

    reply = engine.run(
        EngineRequest(
            system=_SYSTEM,
            prompt=_prompt(locator, candidates),
            context={"ref_issue": ref_issue, "candidate_count": len(candidates)},
        )
    )
    obj = _parse_json_object(reply.text)
    if obj is None:
        return _degrade(locator, candidates)

    by_id = {c.candidate_id: c for c in candidates}
    chosen_id = str(obj.get("chosen_candidate_id", "")).strip()
    chosen = by_id.get(chosen_id)
    if chosen is None:
        raise UnknownCandidateError(
            f"engine chose candidate_id {chosen_id!r}, not in the retrieved shortlist "
            f"{sorted(by_id)}"
        )

    key = str(obj.get("key", "")).strip() or _deterministic_key(chosen, taken=set())
    confidence = str(obj.get("confidence", "")).strip().lower()
    if confidence not in ("low", "medium", "high"):
        confidence = "medium"

    rejected: list[Rejection] = []
    for item in obj.get("rejected") or []:
        if not isinstance(item, dict):
            continue
        cid = str(item.get("candidate_id", "")).strip()
        if cid not in by_id or cid == chosen_id:  # drop invented/self ids
            continue
        rejected.append(Rejection(candidate_id=cid, why=str(item.get("why", "")).strip()))

    return Resolution(candidate=chosen, key=key, rejected=rejected, confidence=confidence)
