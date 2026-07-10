from __future__ import annotations

import json
from pathlib import Path

from mybibliography.bibliography import (
    Entry,
    append_entry,
    find_existing_key,
    render_bibtex,
    render_csl,
)
from mybibliography.retrieval import Candidate

_ARTICLE = Candidate(
    candidate_id="doi:10.1/a",
    type="article",
    title="Paper A",
    authors=["Ada Lovelace", "Alan Turing"],
    year=2021,
    venue="Journal A",
    doi="10.1/a",
    isbn="",
    url="https://doi.org/10.1/a",
)

_BOOK = Candidate(
    candidate_id="isbn:9780134685991",
    type="book",
    title="Effective Java",
    authors=["Joshua Bloch"],
    year=2018,
    venue="Addison-Wesley",
    doi="",
    isbn="9780134685991",
    url="",
)


def test_render_bibtex_article() -> None:
    bibtex = render_bibtex(Entry(key="lovelace2021", candidate=_ARTICLE))
    assert bibtex.startswith("@article{lovelace2021,")
    assert "title = {Paper A}" in bibtex
    assert "author = {Ada Lovelace and Alan Turing}" in bibtex
    assert "journal = {Journal A}" in bibtex
    assert "doi = {10.1/a}" in bibtex


def test_render_bibtex_book() -> None:
    bibtex = render_bibtex(Entry(key="bloch2018", candidate=_BOOK))
    assert bibtex.startswith("@book{bloch2018,")
    assert "publisher = {Addison-Wesley}" in bibtex
    assert "isbn = {9780134685991}" in bibtex


def test_render_csl_article() -> None:
    csl = render_csl(Entry(key="lovelace2021", candidate=_ARTICLE))
    assert csl["id"] == "lovelace2021"
    assert csl["type"] == "article-journal"
    assert csl["DOI"] == "10.1/a"
    assert csl["issued"] == {"date-parts": [[2021]]}


def test_append_entry_writes_both_files(tmp_path: Path) -> None:
    bib_path = tmp_path / "references.bib"
    csl_path = tmp_path / "references.json"
    append_entry(bib_path, csl_path, Entry(key="lovelace2021", candidate=_ARTICLE))

    assert "@article{lovelace2021," in bib_path.read_text()
    csl_entries = json.loads(csl_path.read_text())
    assert csl_entries[0]["id"] == "lovelace2021"


def test_append_entry_is_additive(tmp_path: Path) -> None:
    bib_path = tmp_path / "references.bib"
    csl_path = tmp_path / "references.json"
    append_entry(bib_path, csl_path, Entry(key="lovelace2021", candidate=_ARTICLE))
    append_entry(bib_path, csl_path, Entry(key="bloch2018", candidate=_BOOK))

    assert "lovelace2021" in bib_path.read_text()
    assert "bloch2018" in bib_path.read_text()
    csl_entries = json.loads(csl_path.read_text())
    assert len(csl_entries) == 2


def test_find_existing_key_matches_by_doi(tmp_path: Path) -> None:
    csl_path = tmp_path / "references.json"
    entry = Entry(key="lovelace2021", candidate=_ARTICLE)
    append_entry(tmp_path / "references.bib", csl_path, entry)

    found = find_existing_key(csl_path, [_ARTICLE])
    assert found == "lovelace2021"


def test_find_existing_key_matches_by_isbn(tmp_path: Path) -> None:
    csl_path = tmp_path / "references.json"
    append_entry(tmp_path / "references.bib", csl_path, Entry(key="bloch2018", candidate=_BOOK))

    found = find_existing_key(csl_path, [_BOOK])
    assert found == "bloch2018"


def test_find_existing_key_returns_none_when_absent(tmp_path: Path) -> None:
    csl_path = tmp_path / "references.json"
    assert find_existing_key(csl_path, [_ARTICLE]) is None


def test_find_existing_key_returns_none_for_missing_file(tmp_path: Path) -> None:
    assert find_existing_key(tmp_path / "nope.json", [_ARTICLE]) is None
