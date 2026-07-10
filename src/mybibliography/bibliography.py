from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from mybibliography.retrieval import Candidate

BIB_FILENAME = "references.bib"
CSL_FILENAME = "references.json"


@dataclass(frozen=True)
class Entry:
    key: str
    candidate: Candidate


def identifiers_of(candidate: Candidate) -> list[str]:
    # Every identifier a candidate carries, normalized -- used for dedupe
    # lookups so a hit on any one of them counts as "already cataloged".
    ids = []
    if candidate.doi:
        ids.append(f"doi:{candidate.doi.lower()}")
    if candidate.isbn:
        ids.append(f"isbn:{candidate.isbn}")
    if candidate.candidate_id.startswith("arxiv:"):
        ids.append(candidate.candidate_id.lower())
    return ids


def find_existing_key(csl_path: Path, candidates: list[Candidate]) -> str | None:
    if not csl_path.exists():
        return None
    try:
        entries = json.loads(csl_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, ValueError):
        return None
    wanted: set[str] = set()
    for cand in candidates:
        wanted.update(identifiers_of(cand))
    if not wanted:
        return None
    for entry in entries:
        existing_ids: set[str] = set()
        if entry.get("DOI"):
            existing_ids.add(f"doi:{entry['DOI'].lower()}")
        if entry.get("ISBN"):
            existing_ids.add(f"isbn:{entry['ISBN']}")
        note = entry.get("note") or ""
        match = re.search(r"arxiv:\S+", note.lower())
        if match:
            existing_ids.add(match.group(0))
        if existing_ids & wanted:
            return entry.get("id")
    return None


def _bibtex_authors(authors: list[str]) -> str:
    return " and ".join(authors)


def render_bibtex(entry: Entry) -> str:
    c = entry.candidate
    entry_type = "article" if c.type == "article" else "book"
    fields: list[tuple[str, str]] = []
    if c.title:
        fields.append(("title", c.title))
    if c.authors:
        fields.append(("author", _bibtex_authors(c.authors)))
    if c.year:
        fields.append(("year", str(c.year)))
    if entry_type == "article" and c.venue:
        fields.append(("journal", c.venue))
    if entry_type == "book" and c.venue:
        fields.append(("publisher", c.venue))
    if c.doi:
        fields.append(("doi", c.doi))
    if c.isbn:
        fields.append(("isbn", c.isbn))
    if c.url:
        fields.append(("url", c.url))
    if c.candidate_id.startswith("arxiv:"):
        fields.append(("note", c.candidate_id))

    body = ",\n".join(f"  {name} = {{{value}}}" for name, value in fields)
    return f"@{entry_type}{{{entry.key},\n{body}\n}}\n"


def render_csl(entry: Entry) -> dict:
    c = entry.candidate
    csl_type = "article-journal" if c.type == "article" else "book"
    authors = [
        {"family": parts[-1], "given": " ".join(parts[:-1])} if len(parts) > 1
        else {"family": parts[0] if parts else name, "given": ""}
        for name in c.authors
        for parts in [name.split()]
    ]
    obj: dict = {
        "id": entry.key,
        "type": csl_type,
        "title": c.title,
        "author": authors,
    }
    if c.year:
        obj["issued"] = {"date-parts": [[c.year]]}
    if c.type == "article" and c.venue:
        obj["container-title"] = c.venue
    if c.type == "book" and c.venue:
        obj["publisher"] = c.venue
    if c.doi:
        obj["DOI"] = c.doi
    if c.isbn:
        obj["ISBN"] = c.isbn
    if c.url:
        obj["URL"] = c.url
    if c.candidate_id.startswith("arxiv:"):
        obj["note"] = c.candidate_id
    return obj


def append_entry(tree_bib: Path, tree_csl: Path, entry: Entry) -> None:
    bibtex = render_bibtex(entry)
    existing_bib = tree_bib.read_text(encoding="utf-8") if tree_bib.exists() else ""
    separator = "\n" if existing_bib and not existing_bib.endswith("\n\n") else ""
    tree_bib.write_text(existing_bib + separator + bibtex, encoding="utf-8")

    csl_entries: list[dict] = []
    if tree_csl.exists():
        try:
            csl_entries = json.loads(tree_csl.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, ValueError):
            csl_entries = []
    csl_entries.append(render_csl(entry))
    tree_csl.write_text(json.dumps(csl_entries, indent=2) + "\n", encoding="utf-8")
