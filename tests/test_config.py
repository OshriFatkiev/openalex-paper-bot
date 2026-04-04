from __future__ import annotations

from pathlib import Path

import pytest

from openalex_paper_bot.config import find_project_root, load_watchlist


def test_find_project_root_uses_watchlist_example_as_marker(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    nested = project_root / "src" / "pkg"
    nested.mkdir(parents=True)
    (project_root / "pyproject.toml").write_text("[project]\nname='x'\n", encoding="utf-8")
    (project_root / "watchlist.example.yaml").write_text("targets: []\n", encoding="utf-8")

    assert find_project_root(nested) == project_root.resolve()


def test_load_watchlist_missing_file_points_to_example(tmp_path: Path) -> None:
    watchlist_path = tmp_path / "watchlist.yaml"
    (tmp_path / "watchlist.example.yaml").write_text("targets: []\n", encoding="utf-8")

    with pytest.raises(FileNotFoundError) as exc_info:
        load_watchlist(watchlist_path)

    assert "watchlist.example.yaml" in str(exc_info.value)
