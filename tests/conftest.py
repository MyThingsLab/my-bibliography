from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
from mythings.engine import EngineRequest, EngineResult

from mybibliography.retrieval import (
    CROSSREF_WORKS_ENDPOINT,
    OPENLIBRARY_BOOKS_ENDPOINT,
    OPENLIBRARY_SEARCH_ENDPOINT,
)


@pytest.fixture(autouse=True)
def _clean_git_env(monkeypatch: pytest.MonkeyPatch) -> None:
    # pre-commit runs hooks with GIT_DIR/GIT_INDEX_FILE set; they leak into the
    # git subprocesses these tests spawn (and into isolation.Workspace) and break
    # worktree ops on the throwaway repo. Real runs are not inside a hook.
    for var in ("GIT_DIR", "GIT_INDEX_FILE", "GIT_WORK_TREE", "GIT_OBJECT_DIRECTORY"):
        monkeypatch.delenv(var, raising=False)


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


def fake_fetch(url: str, *, data: bytes | None = None, headers: dict | None = None) -> bytes:
    if url.startswith(f"{CROSSREF_WORKS_ENDPOINT}/"):
        return json.dumps(CROSSREF_DOI_JSON).encode()
    if url.startswith(CROSSREF_WORKS_ENDPOINT):
        return json.dumps(CROSSREF_SEARCH_JSON).encode()
    if "export.arxiv.org" in url:
        return ARXIV_ATOM.encode()
    if url.startswith(OPENLIBRARY_BOOKS_ENDPOINT):
        return json.dumps(OPENLIBRARY_BOOKS_JSON).encode()
    if url.startswith(OPENLIBRARY_SEARCH_ENDPOINT):
        return json.dumps(OPENLIBRARY_SEARCH_JSON).encode()
    raise AssertionError(f"unexpected fetch url: {url}")


def empty_fetch(url: str, *, data: bytes | None = None, headers: dict | None = None) -> bytes:
    if "export.arxiv.org" in url:
        return b'<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom"></feed>'
    if url.startswith(f"{CROSSREF_WORKS_ENDPOINT}/"):
        # A single-work lookup (doi:<id>) for an unknown DOI: no "message".
        return json.dumps({"message": None}).encode()
    if url.startswith(CROSSREF_WORKS_ENDPOINT):
        return json.dumps({"message": {"items": []}}).encode()
    if url.startswith(OPENLIBRARY_SEARCH_ENDPOINT):
        return json.dumps({"docs": []}).encode()
    if url.startswith(OPENLIBRARY_BOOKS_ENDPOINT):
        return json.dumps({}).encode()
    raise AssertionError(f"unexpected fetch url: {url}")


class ScriptedEngine:
    def __init__(self, reply: str) -> None:
        self.reply = reply
        self.calls: list[EngineRequest] = []

    def run(self, request: EngineRequest) -> EngineResult:
        self.calls.append(request)
        return EngineResult(text=self.reply)


class SpyEngine:
    def __init__(self) -> None:
        self.calls: list[EngineRequest] = []

    def run(self, request: EngineRequest) -> EngineResult:
        self.calls.append(request)
        return EngineResult(text="")


class FakeRunner:
    # Mocks only the `gh` subprocess boundary.
    def __init__(
        self,
        *,
        title: str = "Reference request",
        body: str = "doi:10.1234/gnn",
        existing_pr: dict | None = None,
    ) -> None:
        self.calls: list[list[str]] = []
        self.title = title
        self.body = body
        self.existing_pr = existing_pr

    def __call__(self, argv: list[str]) -> str:
        self.calls.append(argv)
        if argv[:2] == ["issue", "view"]:
            return json.dumps({"number": int(argv[2]), "title": self.title, "body": self.body})
        if argv[:2] == ["pr", "list"]:
            return json.dumps([self.existing_pr] if self.existing_pr else [])
        if argv[:2] == ["pr", "create"]:
            return "https://github.com/owner/name/pull/7\n"
        if argv[:2] == ["issue", "comment"]:
            return "https://github.com/owner/name/issues/5#issuecomment-1\n"
        raise AssertionError(f"unexpected gh call: {argv}")


def make_repo(tmp_path: Path) -> Path:
    origin = tmp_path / "origin.git"
    subprocess.run(["git", "init", "--bare", str(origin)], check=True, capture_output=True)
    repo = tmp_path / "work"
    repo.mkdir()
    (repo / "README.md").write_text("# bibliography\n", encoding="utf-8")

    def _git(*argv: str) -> None:
        subprocess.run(["git", "-C", str(repo), *argv], check=True, capture_output=True, text=True)

    _git("init", "-b", "main")
    _git("config", "user.email", "t@example.com")
    _git("config", "user.name", "Bibliographer")
    _git("add", "-A")
    _git("commit", "-m", "init")
    _git("remote", "add", "origin", str(origin))
    _git("push", "-u", "origin", "main")
    return repo


def branch_file(repo: Path, branch: str, path: str) -> str:
    origin = repo.parent / "origin.git"
    proc = subprocess.run(
        ["git", "-C", str(origin), "show", f"{branch}:{path}"],
        capture_output=True,
        text=True,
    )
    return proc.stdout
