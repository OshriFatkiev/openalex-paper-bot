from __future__ import annotations

from pathlib import Path

from openalex_paper_bot.cli import main
from openalex_paper_bot.storage import read_state


def test_reset_state_command_resets_state_with_yes_flag(tmp_path: Path, monkeypatch, capsys) -> None:
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


def test_reset_state_command_aborts_without_confirmation(tmp_path: Path, monkeypatch, capsys) -> None:
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
