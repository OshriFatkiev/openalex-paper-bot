from __future__ import annotations

from datetime import UTC, datetime

from openalex_paper_bot.models import State
from openalex_paper_bot.storage import read_state, reset_state, updated_state, write_state


def test_read_state_returns_default_for_missing_file(tmp_path) -> None:
    state = read_state(tmp_path / "state.json")
    assert state.sent_work_ids == []
    assert state.sent_paper_signatures == []
    assert state.last_run_at is None


def test_write_state_roundtrip_and_dedupes_ids(tmp_path) -> None:
    executed_at = datetime(2026, 4, 3, 6, 0, tzinfo=UTC)
    initial = State(
        sent_work_ids=["https://openalex.org/W1"],
        sent_paper_signatures=["title:paper one|lead:alice"],
        last_run_at=None,
    )
    updated = updated_state(
        initial,
        new_work_ids=["https://openalex.org/W2", "https://openalex.org/W1"],
        new_paper_signatures=["doi:10.1000/example", "title:paper one|lead:alice"],
        executed_at=executed_at,
    )

    path = tmp_path / "state.json"
    write_state(path, updated)
    loaded = read_state(path)

    assert loaded.sent_work_ids == [
        "https://openalex.org/W1",
        "https://openalex.org/W2",
    ]
    assert loaded.sent_paper_signatures == [
        "doi:10.1000/example",
        "title:paper one|lead:alice",
    ]
    assert loaded.last_run_at == executed_at


def test_reset_state_writes_default_empty_state(tmp_path) -> None:
    path = tmp_path / "state.json"
    path.write_text(
        '{"sent_work_ids":["https://openalex.org/W1"],"sent_paper_signatures":["x"],"last_run_at":"2026-04-04T00:00:00Z"}',
        encoding="utf-8",
    )

    reset_state(path)
    loaded = read_state(path)

    assert loaded.sent_work_ids == []
    assert loaded.sent_paper_signatures == []
    assert loaded.last_run_at is None
