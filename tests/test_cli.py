from __future__ import annotations

from pathlib import Path

import pytest

from conftest import fake_fetch, fake_gh, make_repo
from mybibliography import cli


def test_cli_add_noop_degrades_and_prints(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = make_repo(tmp_path)
    fake = fake_gh(body="doi:10.1234/gnn")
    real_make = cli.Bibliography

    def _patched(*args, **kwargs):
        b = real_make(*args, **kwargs)
        b.runner = fake
        b.fetch = fake_fetch
        return b

    monkeypatch.setattr(cli, "Bibliography", _patched)

    code = cli.main(
        [
            "add",
            "--issue", "5",
            "--repo", "owner/name",
            "--repo-root", str(repo),
            "--ledger", str(tmp_path / "ledger.jsonl"),
        ]
    )
    out = capsys.readouterr().out
    assert code == 0
    assert "success" in out


def test_cli_requires_subcommand() -> None:
    with pytest.raises(SystemExit):
        cli.main([])


def test_cli_locator_override(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = make_repo(tmp_path)
    fake = fake_gh(body="no locator in body")
    real_make = cli.Bibliography

    def _patched(*args, **kwargs):
        b = real_make(*args, **kwargs)
        b.runner = fake
        b.fetch = fake_fetch
        return b

    monkeypatch.setattr(cli, "Bibliography", _patched)

    code = cli.main(
        [
            "add",
            "--issue", "5",
            "--locator", "doi:10.1234/gnn",
            "--repo", "owner/name",
            "--repo-root", str(repo),
            "--ledger", str(tmp_path / "ledger.jsonl"),
            "--no-pr",
            "--no-comment",
        ]
    )
    out = capsys.readouterr().out
    assert code == 0
    assert "success" in out
