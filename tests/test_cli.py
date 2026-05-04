from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from openalex_paper_bot.cli import main
from openalex_paper_bot.storage import read_state


def test_default_command_runs_digest_when_no_subcommand(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def fake_run(*, project_root: Path | None = None, dry_run: bool = False) -> SimpleNamespace:
        assert project_root is None
        assert dry_run is False
        return SimpleNamespace(
            new_paper_count=2,
            fetched_paper_count=5,
            message_sent=True,
            state_path=Path("/tmp/state.json"),
        )

    monkeypatch.setattr("openalex_paper_bot.cli.run", fake_run)

    exit_code = main([])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "Run complete: 2 new papers, 5 matching papers after filters, message_sent=True" in captured.out


def test_default_command_treats_top_level_options_as_run_options(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    expected_project_root = tmp_path / "project"
    expected_project_root.mkdir()

    def fake_run(*, project_root: Path | None = None, dry_run: bool = False) -> SimpleNamespace:
        assert project_root == expected_project_root
        assert dry_run is False
        return SimpleNamespace(
            new_paper_count=0,
            fetched_paper_count=0,
            message_sent=False,
            state_path=expected_project_root / "data" / "state.json",
        )

    monkeypatch.setattr("openalex_paper_bot.cli.run", fake_run)

    exit_code = main(["--project-root", str(expected_project_root)])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "Run complete: 0 new papers, 0 matching papers after filters, message_sent=False" in captured.out


def test_dry_run_flag_passes_through_to_runner(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def fake_run(*, project_root: Path | None = None, dry_run: bool = False) -> SimpleNamespace:
        assert dry_run is True
        return SimpleNamespace(
            new_paper_count=3,
            fetched_paper_count=7,
            message_sent=False,
            state_path=Path("/tmp/state.json"),
        )

    monkeypatch.setattr("openalex_paper_bot.cli.run", fake_run)

    exit_code = main(["run", "--dry-run"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "Dry run complete: 3 new papers" in captured.out
    assert "message_sent=False" in captured.out


def test_dry_run_flag_works_with_implicit_run_command(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def fake_run(*, project_root: Path | None = None, dry_run: bool = False) -> SimpleNamespace:
        assert dry_run is True
        return SimpleNamespace(
            new_paper_count=1,
            fetched_paper_count=1,
            message_sent=False,
            state_path=Path("/tmp/state.json"),
        )

    monkeypatch.setattr("openalex_paper_bot.cli.run", fake_run)

    exit_code = main(["--dry-run"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "Dry run complete: 1 new papers" in captured.out


def test_reset_state_command_resets_state_with_yes_flag(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    project_root = tmp_path / "project"
    data_dir = project_root / "data"
    data_dir.mkdir(parents=True)
    (project_root / "pyproject.toml").write_text("[project]\nname='x'\n", encoding="utf-8")
    (project_root / "watchlist.example.yaml").write_text("targets: []\n", encoding="utf-8")
    (data_dir / "state.json").write_text(
        (
            "{\n"
            '  "sent_work_ids": ["https://openalex.org/W1"],\n'
            '  "sent_paper_signatures": ["doi:10.1000/example"],\n'
            '  "last_run_at": "2026-04-04T00:00:00Z"\n'
            "}\n"
        ),
        encoding="utf-8",
    )

    exit_code = main(["reset-state", "--project-root", str(project_root), "--yes"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "Reset state:" in captured.out
    state = read_state(project_root / "data" / "state.json")
    assert state.sent_work_ids == []
    assert state.sent_paper_signatures == []
    assert state.last_run_at is None


def test_reset_state_command_aborts_without_confirmation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    project_root = tmp_path / "project"
    data_dir = project_root / "data"
    data_dir.mkdir(parents=True)
    (project_root / "pyproject.toml").write_text("[project]\nname='x'\n", encoding="utf-8")
    (project_root / "watchlist.example.yaml").write_text("targets: []\n", encoding="utf-8")
    state_path = data_dir / "state.json"
    original = (
        "{\n"
        '  "sent_work_ids": ["https://openalex.org/W1"],\n'
        '  "sent_paper_signatures": ["doi:10.1000/example"],\n'
        '  "last_run_at": "2026-04-04T00:00:00Z"\n'
        "}\n"
    )
    state_path.write_text(original, encoding="utf-8")
    monkeypatch.setattr("builtins.input", lambda _: "n")

    exit_code = main(["reset-state", "--project-root", str(project_root)])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "Aborted." in captured.out
    assert state_path.read_text(encoding="utf-8") == original
