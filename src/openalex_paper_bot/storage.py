"""Read, write, and reset the JSON-backed state file.

The bot keeps its deduplication state in a small JSON file, so this module
handles validation, atomic writes, and reset helpers for that persisted state.
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterable
from datetime import datetime
from pathlib import Path
from typing import cast

from openalex_paper_bot.models import State


def read_state(path: Path) -> State:
    """Read state from disk, returning defaults when the file does not exist.

    Args:
        path: Path to the JSON state file.

    Returns:
        The parsed state object, or a default empty state when the file is
        missing.

    Raises:
        ValueError: If the file contains invalid JSON or schema-invalid state.
    """
    if not path.exists():
        return State()

    try:
        raw_data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON in state file {path}: {exc}") from exc

    try:
        return cast(State, State.model_validate(raw_data))
    except Exception as exc:  # pragma: no cover - pydantic already formats the details.
        raise ValueError(f"Invalid state data in {path}: {exc}") from exc


def write_state(path: Path, state: State) -> None:
    """Write state atomically to disk.

    Args:
        path: Destination path for the JSON state file.
        state: State object to persist.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(f"{path.suffix}.tmp")
    tmp_path.write_text(
        state.model_dump_json(indent=2, exclude_none=False) + "\n",
        encoding="utf-8",
    )
    os.replace(tmp_path, path)


def reset_state(path: Path) -> State:
    """Reset the persisted state file to the default empty state.

    Args:
        path: Destination path for the JSON state file.

    Returns:
        The default empty state that was written to disk.
    """
    state = State()
    write_state(path, state)
    return state


def updated_state(
    state: State,
    *,
    new_work_ids: Iterable[str],
    new_paper_signatures: Iterable[str] = (),
    executed_at: datetime,
) -> State:
    """Create the state that should be persisted after a run.

    Args:
        state: Previously stored state.
        new_work_ids: Raw OpenAlex work IDs sent during the run.
        new_paper_signatures: Collapsed equivalence signatures sent during the
            run.
        executed_at: Timestamp to store as ``last_run_at``.

    Returns:
        A new state object containing the merged IDs and timestamp.
    """
    sent_work_ids = sorted({*state.sent_work_ids, *new_work_ids})
    sent_paper_signatures = sorted({*state.sent_paper_signatures, *new_paper_signatures})
    return State(
        sent_work_ids=sent_work_ids,
        sent_paper_signatures=sent_paper_signatures,
        last_run_at=executed_at,
    )
