from __future__ import annotations

import json
import urllib.parse
from dataclasses import dataclass, field
from xml.etree import ElementTree as ET

from mythings.http import Fetcher, http_get

CROSSREF_WORKS_ENDPOINT = "https://api.crossref.org/works"
ARXIV_ENDPOINT = "http://export.arxiv.org/api/query"
OPENLIBRARY_BOOKS_ENDPOINT = "https://openlibrary.org/api/books"
OPENLIBRARY_SEARCH_ENDPOINT = "https://openlibrary.org/search.json"

_ATOM = {"a": "http://www.w3.org/2005/Atom"}

_STOPWORDS = frozenset(
    "a an and are as at be by for from how in into is it of on or the to via with query".split()
)


@dataclass(frozen=True)
class Candidate:
    candidate_id: str
    type: str  # "article" | "book"
    title: str
    authors: list[str] = field(default_factory=list)
    year: int | None = None
    venue: str = ""
    doi: str = ""
    isbn: str = ""
    url: str = ""


@dataclass(frozen=True)
class Locator:
    kind: str  # "doi" | "arxiv" | "isbn" | "query"
    value: str


_LOCATOR_PREFIXES = (("doi:", "doi"), ("arxiv:", "arxiv"), ("isbn:", "isbn"), ("query:", "query"))


def parse_locator(body: str) -> Locator | None:
    for line in body.splitlines():
        line = line.strip()
        for prefix, kind in _LOCATOR_PREFIXES:
            if line.lower().startswith(prefix):
                value = line[len(prefix):].strip().strip('"')
                if value:
                    return Locator(kind=kind, value=value)
    return None


def tokenize(text: str) -> list[str]:
    out: list[str] = []
    word: list[str] = []
    for ch in text.lower():
        if ch.isalnum():
            word.append(ch)
        elif word:
            out.append("".join(word))
            word = []
    if word:
        out.append("".join(word))
    return out


def query_terms(query: str) -> list[str]:
    seen: set[str] = set()
    terms: list[str] = []
    for tok in tokenize(query):
        if tok in _STOPWORDS or len(tok) < 2 or tok in seen:
            continue
        seen.add(tok)
        terms.append(tok)
    return terms


def _isbn13(raw: str) -> str:
    # Normalize ISBN-10 -> ISBN-13 (978 prefix, recomputed check digit) so the
    # same book isn't recorded twice under two identifiers.
    digits = "".join(ch for ch in raw if ch.isalnum())
    if len(digits) == 13:
        return digits
    if len(digits) != 10:
        return digits
    core = "978" + digits[:9]
    total = sum((1 if i % 2 == 0 else 3) * int(d) for i, d in enumerate(core))
    check = (10 - total % 10) % 10
    return core + str(check)


def _year_of_crossref(item: dict) -> int | None:
    for key in ("published-print", "published-online", "published", "issued"):
        parts = (item.get(key) or {}).get("date-parts")
        if parts and parts[0] and parts[0][0]:
            return int(parts[0][0])
    return None


def _authors_of_crossref(item: dict) -> list[str]:
    out = []
    for a in item.get("author", []) or []:
        name = " ".join(filter(None, [a.get("given"), a.get("family")])).strip()
        if name:
            out.append(name)
    return out


def _crossref_candidate(item: dict) -> Candidate:
    doi = (item.get("DOI") or "").strip()
    title = " ".join((item.get("title") or [""])[0].split())
    container = item.get("container-title")
    venue = " ".join(container[0].split()) if container else ""
    url = (item.get("URL") or (f"https://doi.org/{doi}" if doi else "")).strip()
    return Candidate(
        candidate_id=f"doi:{doi}" if doi else f"crossref:{title}",
        type="article",
        title=title,
        authors=_authors_of_crossref(item),
        year=_year_of_crossref(item),
        venue=venue,
        doi=doi,
        isbn="",
        url=url,
    )


def fetch_crossref_doi(doi: str, *, fetch: Fetcher = http_get) -> list[Candidate]:
    doi = doi.strip()
    if not doi:
        return []
    url = f"{CROSSREF_WORKS_ENDPOINT}/{urllib.parse.quote(doi, safe='')}"
    try:
        raw = fetch(url)
    except Exception:
        return []
    payload = json.loads(raw)
    item = payload.get("message")
    if not item:
        return []
    return [_crossref_candidate(item)]


def search_crossref(query: str, *, fetch: Fetcher = http_get, limit: int = 10) -> list[Candidate]:
    if not query:
        return []
    params = urllib.parse.urlencode({"query.bibliographic": query, "rows": limit})
    try:
        raw = fetch(f"{CROSSREF_WORKS_ENDPOINT}?{params}")
    except Exception:
        return []
    payload = json.loads(raw)
    items = (payload.get("message") or {}).get("items") or []
    return [_crossref_candidate(item) for item in items]


def _year_of_arxiv(published: str | None) -> int | None:
    if not published or len(published) < 4 or not published[:4].isdigit():
        return None
    return int(published[:4])


def fetch_arxiv_id(arxiv_id: str, *, fetch: Fetcher = http_get) -> list[Candidate]:
    arxiv_id = arxiv_id.strip()
    if not arxiv_id:
        return []
    params = urllib.parse.urlencode({"id_list": arxiv_id})
    try:
        raw = fetch(f"{ARXIV_ENDPOINT}?{params}")
    except Exception:
        return []
    return _parse_arxiv_feed(raw)


def search_arxiv(query: str, *, fetch: Fetcher = http_get, limit: int = 10) -> list[Candidate]:
    if not query:
        return []
    params = urllib.parse.urlencode(
        {
            "search_query": f"all:{query}",
            "start": 0,
            "max_results": limit,
            "sortBy": "relevance",
            "sortOrder": "descending",
        }
    )
    try:
        raw = fetch(f"{ARXIV_ENDPOINT}?{params}")
    except Exception:
        return []
    return _parse_arxiv_feed(raw)


def _parse_arxiv_feed(raw: bytes) -> list[Candidate]:
    root = ET.fromstring(raw)
    candidates: list[Candidate] = []
    for entry in root.findall("a:entry", _ATOM):
        eid = (entry.findtext("a:id", default="", namespaces=_ATOM) or "").strip()
        arxiv_id = eid.rsplit("/abs/", 1)[-1] if "/abs/" in eid else eid.rsplit("/", 1)[-1]
        title = " ".join((entry.findtext("a:title", "", _ATOM) or "").split())
        authors = [
            (a.findtext("a:name", "", _ATOM) or "").strip()
            for a in entry.findall("a:author", _ATOM)
        ]
        candidates.append(
            Candidate(
                candidate_id=f"arxiv:{arxiv_id}",
                type="article",
                title=title,
                authors=[a for a in authors if a],
                year=_year_of_arxiv(entry.findtext("a:published", None, _ATOM)),
                venue="arXiv",
                doi="",
                isbn="",
                url=eid,
            )
        )
    return candidates


def _openlibrary_candidate(data: dict, *, isbn: str = "") -> Candidate:
    title = (data.get("title") or "").strip()
    authors = [a.get("name", "").strip() for a in data.get("authors", []) if a.get("name")]
    year = None
    published = data.get("publish_date") or ""
    for token in published.split():
        if token.isdigit() and len(token) == 4:
            year = int(token)
    publishers = data.get("publishers") or []
    venue = publishers[0].get("name", "") if publishers and isinstance(publishers[0], dict) else (
        publishers[0] if publishers else ""
    )
    identifiers = data.get("identifiers") or {}
    isbn_13 = (identifiers.get("isbn_13") or [None])[0]
    isbn_10 = (identifiers.get("isbn_10") or [None])[0]
    resolved_isbn = _isbn13(isbn_13 or isbn_10 or isbn)
    return Candidate(
        candidate_id=f"isbn:{resolved_isbn}" if resolved_isbn else f"openlibrary:{title}",
        type="book",
        title=title,
        authors=authors,
        year=year,
        venue=venue,
        doi="",
        isbn=resolved_isbn,
        url=(data.get("url") or "").strip(),
    )


def fetch_openlibrary_isbn(isbn: str, *, fetch: Fetcher = http_get) -> list[Candidate]:
    isbn = isbn.strip()
    if not isbn:
        return []
    key = f"ISBN:{isbn}"
    params = urllib.parse.urlencode({"bibkeys": key, "format": "json", "jscmd": "data"})
    try:
        raw = fetch(f"{OPENLIBRARY_BOOKS_ENDPOINT}?{params}")
    except Exception:
        return []
    payload = json.loads(raw)
    data = payload.get(key)
    if not data:
        return []
    return [_openlibrary_candidate(data, isbn=isbn)]


def search_openlibrary(
    query: str, *, fetch: Fetcher = http_get, limit: int = 10
) -> list[Candidate]:
    if not query:
        return []
    params = urllib.parse.urlencode({"q": query, "limit": limit})
    try:
        raw = fetch(f"{OPENLIBRARY_SEARCH_ENDPOINT}?{params}")
    except Exception:
        return []
    payload = json.loads(raw)
    candidates: list[Candidate] = []
    for doc in payload.get("docs", []) or []:
        title = (doc.get("title") or "").strip()
        authors = doc.get("author_name") or []
        isbn_list = doc.get("isbn") or []
        isbn = _isbn13(isbn_list[0]) if isbn_list else ""
        key = doc.get("key", "").strip()
        candidates.append(
            Candidate(
                candidate_id=f"isbn:{isbn}" if isbn else f"openlibrary:{key or title}",
                type="book",
                title=title,
                authors=[a.strip() for a in authors if a.strip()],
                year=doc.get("first_publish_year"),
                venue=(doc.get("publisher") or [""])[0] if doc.get("publisher") else "",
                doi="",
                isbn=isbn,
                url=f"https://openlibrary.org{key}" if key else "",
            )
        )
    return candidates


def _score(candidate: Candidate, query_tokens: set[str]) -> tuple[int, str]:
    haystack = set(tokenize(candidate.title))
    for a in candidate.authors:
        haystack |= set(tokenize(a))
    overlap = len(query_tokens & haystack)
    return (overlap, candidate.candidate_id)


def retrieve(locator: Locator, *, fetch: Fetcher = http_get, top: int = 5) -> list[Candidate]:
    found: list[Candidate] = []
    if locator.kind == "doi":
        found = fetch_crossref_doi(locator.value, fetch=fetch)
    elif locator.kind == "arxiv":
        found = fetch_arxiv_id(locator.value, fetch=fetch)
    elif locator.kind == "isbn":
        found = fetch_openlibrary_isbn(locator.value, fetch=fetch)
    elif locator.kind == "query":
        found = search_crossref(locator.value, fetch=fetch, limit=top) + search_openlibrary(
            locator.value, fetch=fetch, limit=top
        )

    deduped: dict[str, Candidate] = {}
    for cand in found:
        key = cand.doi.lower() or cand.isbn or cand.candidate_id
        deduped.setdefault(key, cand)

    query_tokens = set(query_terms(locator.value))
    ranked = sorted(deduped.values(), key=lambda c: _score(c, query_tokens), reverse=True)
    return ranked[:top]
