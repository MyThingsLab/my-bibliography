from __future__ import annotations

import json
from pathlib import Path

import pytest

# Shared fakes come from mythings.testing (plain imports; aliased fixture
# re-export + getfixturevalue wrapper per core docs/CONVENTIONS.md).
from mythings.testing import FakeGh, GitRepo, ScriptedEngine, make_git_repo
from mythings.testing import clean_git_env as _shared_clean_git_env  # noqa: F401
from mythings.testing import fake_fetch as _fake_fetch

from mybibliography.retrieval import (
    CROSSREF_WORKS_ENDPOINT,
    OPENLIBRARY_BOOKS_ENDPOINT,
    OPENLIBRARY_SEARCH_ENDPOINT,
)

__all__ = ["ScriptedEngine"]


@pytest.fixture(autouse=True)
def _clean_git_env(request: pytest.FixtureRequest) -> None:
    # Real git worktrees in every test; hook-launched pytest (pre-commit)
    # must not leak GIT_* into them.
    request.getfixturevalue("_shared_clean_git_env")


CROSSREF_DOI_JSON = {
    "message": {
        "DOI": "10.1234/gnn",
        "title": ["Graph Neural Networks for Physics"],
        "author": [{"given": "Ada", "family": "Lovelace"}],
        "container-title": ["Journal of Graphs"],
        "issued": {"date-parts": [[2021]]},
        "URL": "https://doi.org/10.1234/gnn",
    }
}

CROSSREF_SEARCH_JSON = {
    "message": {
        "items": [
            {
                "DOI": "10.1234/gnn",
                "title": ["Graph Neural Networks for Physics"],
                "author": [{"given": "Ada", "family": "Lovelace"}],
                "container-title": ["Journal of Graphs"],
                "issued": {"date-parts": [[2021]]},
                "URL": "https://doi.org/10.1234/gnn",
            }
        ]
    }
}

ARXIV_ATOM = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <id>http://arxiv.org/abs/2101.00001v1</id>
    <title>Graph Neural Networks for Physics Simulation</title>
    <summary>We study graph neural networks applied to physical systems.</summary>
    <published>2021-01-01T00:00:00Z</published>
    <author><name>Ada Lovelace</name></author>
  </entry>
</feed>
"""

OPENLIBRARY_BOOKS_JSON = {
    "ISBN:9780134685991": {
        "title": "Effective Java",
        "authors": [{"name": "Joshua Bloch"}],
        "publish_date": "2018",
        "publishers": [{"name": "Addison-Wesley"}],
        "identifiers": {"isbn_13": ["9780134685991"]},
        "url": "https://openlibrary.org/books/OL1234M",
    }
}

OPENLIBRARY_SEARCH_JSON = {
    "docs": [
        {
            "title": "Effective Java",
            "author_name": ["Joshua Bloch"],
            "first_publish_year": 2018,
            "isbn": ["9780134685991"],
            "publisher": ["Addison-Wesley"],
            "key": "/works/OL1234W",
        }
    ]
}

# Insertion order matters: the single-work path (endpoint + "/") must win the
# substring match over the bare search endpoint.
fake_fetch = _fake_fetch(
    {
        f"{CROSSREF_WORKS_ENDPOINT}/": CROSSREF_DOI_JSON,
        CROSSREF_WORKS_ENDPOINT: CROSSREF_SEARCH_JSON,
        "export.arxiv.org": ARXIV_ATOM,
        OPENLIBRARY_BOOKS_ENDPOINT: OPENLIBRARY_BOOKS_JSON,
        OPENLIBRARY_SEARCH_ENDPOINT: OPENLIBRARY_SEARCH_JSON,
    }
)

empty_fetch = _fake_fetch(
    {
        "export.arxiv.org": b'<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom"></feed>',
        # A single-work lookup (doi:<id>) for an unknown DOI: no "message".
        f"{CROSSREF_WORKS_ENDPOINT}/": {"message": None},
        CROSSREF_WORKS_ENDPOINT: {"message": {"items": []}},
        OPENLIBRARY_SEARCH_ENDPOINT: {"docs": []},
        OPENLIBRARY_BOOKS_ENDPOINT: {},
    }
)


def fake_gh(
    *,
    title: str = "Reference request",
    body: str = "doi:10.1234/gnn",
    existing_pr: dict | None = None,
) -> FakeGh:
    def issue_view(argv: list[str]) -> str:
        return json.dumps({"number": int(argv[2]), "title": title, "body": body})

    return FakeGh(
        {
            ("issue", "view"): issue_view,
            ("pr", "list"): json.dumps([existing_pr] if existing_pr else []),
            ("pr", "create"): "https://github.com/owner/name/pull/7\n",
            ("issue", "comment"): "https://github.com/owner/name/issues/5#issuecomment-1\n",
        }
    )


def make_repo(tmp_path: Path) -> Path:
    return make_git_repo(tmp_path, files={"README.md": "# bibliography\n"}).path


def branch_file(repo: Path, branch: str, path: str) -> str:
    return GitRepo(path=repo, origin=repo.parent / "origin.git").read_committed(branch, path)
