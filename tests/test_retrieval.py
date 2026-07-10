from __future__ import annotations

from conftest import empty_fetch, fake_fetch
from mybibliography.retrieval import (
    Locator,
    parse_locator,
    retrieve,
    search_crossref,
    search_openlibrary,
)


def test_parse_locator_doi() -> None:
    loc = parse_locator("please add\n\ndoi:10.1234/gnn\n")
    assert loc == Locator(kind="doi", value="10.1234/gnn")


def test_parse_locator_arxiv() -> None:
    loc = parse_locator("arxiv:2101.00001")
    assert loc == Locator(kind="arxiv", value="2101.00001")


def test_parse_locator_isbn() -> None:
    loc = parse_locator("isbn:9780134685991")
    assert loc == Locator(kind="isbn", value="9780134685991")


def test_parse_locator_query() -> None:
    loc = parse_locator('query:"effective java"')
    assert loc == Locator(kind="query", value="effective java")


def test_parse_locator_none_found() -> None:
    assert parse_locator("no locator here") is None


def test_retrieve_doi_returns_one_candidate() -> None:
    candidates = retrieve(Locator("doi", "10.1234/gnn"), fetch=fake_fetch)
    assert len(candidates) == 1
    c = candidates[0]
    assert c.doi == "10.1234/gnn"
    assert c.title == "Graph Neural Networks for Physics"
    assert c.authors == ["Ada Lovelace"]
    assert c.year == 2021


def test_retrieve_arxiv_returns_one_candidate() -> None:
    candidates = retrieve(Locator("arxiv", "2101.00001"), fetch=fake_fetch)
    assert len(candidates) == 1
    assert candidates[0].candidate_id == "arxiv:2101.00001v1"
    assert candidates[0].type == "article"


def test_retrieve_isbn_returns_one_candidate() -> None:
    candidates = retrieve(Locator("isbn", "9780134685991"), fetch=fake_fetch)
    assert len(candidates) == 1
    c = candidates[0]
    assert c.type == "book"
    assert c.isbn == "9780134685991"
    assert c.title == "Effective Java"


def test_retrieve_query_merges_crossref_and_openlibrary() -> None:
    candidates = retrieve(Locator("query", "effective java"), fetch=fake_fetch, top=5)
    types = {c.type for c in candidates}
    assert "article" in types  # from crossref
    assert "book" in types  # from openlibrary


def test_retrieve_caps_at_top() -> None:
    candidates = retrieve(Locator("query", "graph neural"), fetch=fake_fetch, top=1)
    assert len(candidates) == 1


def test_retrieve_no_candidates_returns_empty() -> None:
    assert retrieve(Locator("doi", "10.9999/missing"), fetch=empty_fetch) == []
    assert retrieve(Locator("query", "nothing"), fetch=empty_fetch) == []


def test_search_crossref_parses_items() -> None:
    candidates = search_crossref("graph neural networks", fetch=fake_fetch)
    assert len(candidates) == 1
    assert candidates[0].doi == "10.1234/gnn"


def test_search_openlibrary_parses_docs() -> None:
    candidates = search_openlibrary("effective java", fetch=fake_fetch)
    assert len(candidates) == 1
    assert candidates[0].isbn == "9780134685991"


def test_isbn10_normalizes_to_isbn13() -> None:
    from mybibliography.retrieval import _isbn13

    assert _isbn13("0134685997") == "9780134685991"
