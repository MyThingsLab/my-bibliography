# my-bibliography — agent instructions

You are developing **my-bibliography**, a MyThingsLab My[X] tool.

**Inherited rules:** obey [`./HARNESS.md`](./HARNESS.md) in full — the vendored
MyThingsLab build-harness rules. Do not restate or override them. Anything not
covered here defers to `HARNESS.md`, then `my-things-core/docs/CONVENTIONS.md`.

## This tool

- **Purpose:** given a reference-request issue (`doi:`, `arxiv:`, `isbn:`, or
  `query:` free text), discovers canonical citation metadata **live**
  (Crossref for DOIs/search, arXiv Atom API for arXiv ids, Open Library for
  ISBNs/search), then makes one Engine call to resolve ambiguity and assign a
  citation key, and commits a normalized entry to `references.bib` (BibTeX) +
  `references.json` (CSL-JSON), deduping by DOI/ISBN/arXiv-id.
- **The single Engine call:** "given a reference request and its
  deterministically retrieved candidate shortlist, choose the canonical
  candidate and invent a citation key" → `{chosen_candidate_id, key, rejected,
  confidence}`. The model may only choose a `candidate_id` from the shortlist
  and invent the key — it never supplies title/authors/year/doi/isbn/url
  itself; those are always copied verbatim from the chosen candidate's
  already-retrieved record. Against `NoopEngine`: one candidate auto-chooses
  (`confidence="high"`, deterministic key); several candidates choose the
  top-scored by query-term overlap (`confidence="low"`), the rest `rejected`
  with `why="not the top-scored match"`.
- **Invariants / rules:** exactly one Engine call per run; all retrieval is
  deterministic, LLM-free HTTP (stdlib `urllib`/`json`/`xml.etree`, no SDK, all
  three providers keyless). The HTTP boundary is mocked in the default suite;
  any real-network test is `@pytest.mark.slow`. The Engine reply is never
  trusted for bibliographic field values — only for `chosen_candidate_id` and
  `key`; an unlisted `candidate_id` is a hard failure. Two side effects, both
  routed through `Policy` (`ALLOW` default): a committed bibliography-file PR
  (idempotent per identifier) and an issue comment. **Never merges.** No
  candidates found, or the identifier is already cataloged → skip the Engine
  call entirely, `outcome=skipped`, no PR. Ledger `kind`: `bibliography`.
- **Backlog label:** `my-bibliography`
