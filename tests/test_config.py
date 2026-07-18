from __future__ import annotations

from pathlib import Path

import pytest

from openalex_paper_bot.config import find_project_root, load_runtime_config, load_watchlist


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


def test_load_watchlist_reads_summary_options(tmp_path: Path) -> None:
    watchlist_path = tmp_path / "watchlist.yaml"
    watchlist_path.write_text(
        (
            "targets:\n"
            "  - type: author\n"
            "    name: Yann LeCun\n"
            "summaries:\n"
            "  enabled: true\n"
            "  provider: ollama\n"
            "  model: gemma4:31b\n"
            "  max_chars: 180\n"
        ),
        encoding="utf-8",
    )

    watchlist = load_watchlist(watchlist_path)

    assert watchlist.summaries.enabled is True
    assert watchlist.summaries.provider == "ollama"
    assert watchlist.summaries.model == "gemma4:31b"
    assert watchlist.summaries.max_chars == 180


def test_load_watchlist_defaults_summary_max_chars_to_220(tmp_path: Path) -> None:
    watchlist_path = tmp_path / "watchlist.yaml"
    watchlist_path.write_text(
        "targets:\n  - type: author\n    name: Yann LeCun\n",
        encoding="utf-8",
    )

    watchlist = load_watchlist(watchlist_path)

    assert watchlist.summaries.max_chars == 220


def test_load_runtime_config_reads_ollama_settings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir()
    (project_root / "pyproject.toml").write_text("[project]\nname='x'\n", encoding="utf-8")
    (project_root / "watchlist.yaml").write_text(
        "targets:\n  - type: author\n    name: Yann LeCun\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("OLLAMA_API_KEY", "ollama-key")
    monkeypatch.setenv("OLLAMA_BASE_URL", "https://ollama.com/v1")

    config = load_runtime_config(
        project_root=project_root,
        require_openalex=False,
        require_telegram=False,
    )

    assert config.ollama_api_key == "ollama-key"
    assert config.ollama_base_url == "https://ollama.com/v1"
