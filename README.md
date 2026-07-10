# my-bibliography

[![CI](https://github.com/MyThingsLab/my-bibliography/actions/workflows/ci.yml/badge.svg)](https://github.com/MyThingsLab/my-bibliography/actions/workflows/ci.yml)
[![codecov](https://codecov.io/gh/MyThingsLab/my-bibliography/branch/main/graph/badge.svg)](https://codecov.io/gh/MyThingsLab/my-bibliography)
![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue)
![MIT](https://img.shields.io/badge/license-MIT-green)

A [MyThingsLab](../my-things-core) `My[X]` tool: a **citation cataloger**.
Given a reference-request issue naming one locator (`doi:`, `arxiv:`, `isbn:`,
or `query:` free text), it discovers canonical metadata **live** (Crossref for
DOIs/search, the arXiv Atom API for arXiv ids, Open Library for ISBNs/search),
then makes **one** Engine call to resolve ambiguity and invent a citation key,
and commits a normalized entry to `references.bib` (BibTeX) and
`references.json` (CSL-JSON), deduping by DOI/ISBN/arXiv-id.

It is a cataloging tool, not a synthesis tool: it produces no prose, only a
structured bibliography entry. See the design doc:
[`my-things-core/docs/tools/my-bibliography.md`](../my-things-core/docs/tools/my-bibliography.md).

## Usage

```bash
# Resolve a reference-request issue whose body names a locator (e.g. "doi:10.1234/x")
# into a committed BibTeX + CSL-JSON entry (PR) and an issue comment.
mybibliography add --issue 12 --repo MyThingsLab/study --engine claude-cli

# Override the locator for local testing instead of reading the issue body:
mybibliography add --issue 12 --locator 'arxiv:2101.00001' --no-pr --no-comment
```

Each invocation makes **at most one** Engine call — never more, and not at all
when retrieval finds nothing or the identifier is already cataloged (both
short-circuit to `outcome=skipped`). Against the default `--engine noop` (zero
tokens): a single retrieved candidate auto-chooses with `confidence=high`; with
several candidates, the top-scored by deterministic query-term overlap is
chosen with `confidence=low` and the rest listed as `rejected`.

The Engine may only **choose** a candidate from the already-retrieved
shortlist and **invent** its citation key — every bibliographic field
(title/authors/year/doi/isbn/venue/url) is always copied verbatim from the
retrieved record, never trusted from the reply.

## Retrieval

All three providers are keyless: Crossref, the arXiv Atom API, and Open
Library. Retrieval is deterministic, LLM-free HTTP (stdlib `urllib` +
`json`/`xml.etree`); the network boundary is mocked in the test suite, with one
real-network smoke test marked `@pytest.mark.slow`.

## Install (development)

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ../my-things-core -e ".[dev]"
pytest
```

See [`CLAUDE.md`](CLAUDE.md) for the tool's seams and [`HARNESS.md`](HARNESS.md)
for the inherited build rules.

## License

MIT — see [`LICENSE`](LICENSE).
