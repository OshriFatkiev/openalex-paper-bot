"""Load runtime configuration from the repo, environment, and watchlist YAML.

This module centralizes project-root discovery, lightweight ``.env`` parsing,
watchlist validation, and command-specific runtime configuration assembly.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import cast

import yaml

from openalex_paper_bot.models import RuntimeConfig, WatchlistConfig

logger = logging.getLogger(__name__)


def find_project_root(start: Path | None = None) -> Path:
    """Find the nearest repository root for the bot.

    Args:
        start: Optional path to start searching from. When omitted, the current
            working directory is used.

    Returns:
        The closest parent directory that looks like the project root.

    """
    current = (start or Path.cwd()).resolve()
    candidates = [current, *current.parents]
    for candidate in candidates:
        has_watchlist_marker = (candidate / "watchlist.yaml").exists() or (
            candidate / "watchlist.example.yaml"
        ).exists()
        if has_watchlist_marker and (candidate / "pyproject.toml").exists():
            return candidate
    return current


def load_dotenv(path: Path) -> None:
    """Load a small ``.env`` file without overriding existing variables.

    Args:
        path: Path to the ``.env`` file to parse.

    Raises:
        ValueError: If the file contains a malformed ``KEY=VALUE`` line.

    """
    if not path.exists():
        return

    for line_number, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].strip()
        key, separator, value = line.partition("=")
        if not separator:
            raise ValueError(f"Invalid .env line {line_number}: expected KEY=VALUE.")
        key = key.strip()
        value = value.strip()
        if value and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        os.environ.setdefault(key, value)


def load_watchlist(path: Path) -> WatchlistConfig:
    """Load and validate the YAML watchlist file.

    Args:
        path: Path to the private watchlist YAML file.

    Returns:
        A validated watchlist configuration model.

    Raises:
        FileNotFoundError: If the watchlist file does not exist.
        ValueError: If the YAML contents do not match the expected schema.

    """
    if not path.exists():
        example_path = path.with_name("watchlist.example.yaml")
        message = f"Watchlist file not found: {path}"
        if example_path.exists():
            message += f". Create it from {example_path}."
        raise FileNotFoundError(message)

    raw_data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    try:
        config = cast(WatchlistConfig, WatchlistConfig.model_validate(raw_data))
    except Exception as exc:  # pragma: no cover - pydantic already formats the details.
        raise ValueError(f"Invalid watchlist configuration in {path}: {exc}") from exc
    target_count = len(config.targets)
    query_count = len(config.global_queries)
    logger.info("Loaded watchlist: %d targets, %d global queries", target_count, query_count)
    return config


def load_runtime_config(
    *,
    project_root: Path | None = None,
    require_openalex: bool,
    require_telegram: bool,
) -> RuntimeConfig:
    """Load runtime configuration for a CLI command.

    Args:
        project_root: Optional explicit project root. When omitted, the project
            root is discovered automatically.
        require_openalex: Whether ``OPENALEX_API_KEY`` must be present.
        require_telegram: Whether Telegram credentials must be present.

    Returns:
        A fully populated runtime configuration object.

    Raises:
        ValueError: If required environment variables are missing.

    """
    root = find_project_root(project_root)
    load_dotenv(root / ".env")

    watchlist_path = root / "watchlist.yaml"
    state_path = root / "data" / "state.json"
    watchlist = load_watchlist(watchlist_path)

    openalex_api_key = os.getenv("OPENALEX_API_KEY")
    telegram_bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
    telegram_chat_id = os.getenv("TELEGRAM_CHAT_ID")
    github_models_token = os.getenv("GITHUB_MODELS_TOKEN") or os.getenv("GITHUB_TOKEN")

    missing: list[str] = []
    if require_openalex and not openalex_api_key:
        missing.append("OPENALEX_API_KEY")
    if require_telegram and not telegram_bot_token:
        missing.append("TELEGRAM_BOT_TOKEN")
    if require_telegram and not telegram_chat_id:
        missing.append("TELEGRAM_CHAT_ID")
    if missing:
        missing_text = ", ".join(missing)
        raise ValueError(
            f"Missing required environment variables: {missing_text}. Set them in the shell or in {root / '.env'}."
        )

    return RuntimeConfig(
        project_root=root,
        watchlist_path=watchlist_path,
        state_path=state_path,
        watchlist=watchlist,
        openalex_api_key=openalex_api_key,
        telegram_bot_token=telegram_bot_token,
        telegram_chat_id=telegram_chat_id,
        github_models_token=github_models_token,
    )
