from __future__ import annotations

import pytest

from openalex_paper_bot.models import EntityRef, WatchlistConfig, WatchTarget
from openalex_paper_bot.runner import resolve_targets, resolve_topic_fields


class FakeOpenAlexClient:
    def get_author(self, author_id: str) -> EntityRef:
        assert author_id == "A123"
        return EntityRef(
            entity_type="author",
            openalex_id="https://openalex.org/A123",
            display_name="Fetched Author",
        )

    def get_institution(self, inst_id: str) -> EntityRef:
        assert inst_id == "I456"
        return EntityRef(
            entity_type="institution",
            openalex_id="https://openalex.org/I456",
            display_name="Fetched Institution",
        )

    def resolve_author_by_orcid(self, orcid: str) -> EntityRef:
        assert orcid == "0000-0001-2345-6789"
        return EntityRef(
            entity_type="author",
            openalex_id="https://openalex.org/A999",
            display_name="ORCID Author",
        )

    def resolve_institution_by_ror(self, ror: str) -> EntityRef:
        assert ror == "https://ror.org/03yrm5c26"
        return EntityRef(
            entity_type="institution",
            openalex_id="https://openalex.org/I999",
            display_name="ROR Institution",
        )

    def resolve_author(self, name: str) -> EntityRef:
        return EntityRef(
            entity_type="author",
            openalex_id="https://openalex.org/A111",
            display_name=name,
        )

    def resolve_institution(self, name: str) -> EntityRef:
        return EntityRef(
            entity_type="institution",
            openalex_id="https://openalex.org/I111",
            display_name=name,
        )

    def get_field(self, field_id: str) -> EntityRef:
        assert field_id == "17"
        return EntityRef(
            entity_type="field",
            openalex_id="https://openalex.org/fields/17",
            display_name="Computer Science",
        )

    def resolve_field(self, name: str) -> EntityRef:
        return EntityRef(
            entity_type="field",
            openalex_id="https://openalex.org/fields/31",
            display_name="Physics and Astronomy" if name == "Physics" else name,
        )


def test_watch_target_validates_type_specific_identifier_fields() -> None:
    WatchTarget(type="author", orcid="0000-0001-2345-6789")
    WatchTarget(type="institution", ror="03yrm5c26")

    with pytest.raises(ValueError):
        WatchTarget(type="institution", orcid="0000-0001-2345-6789")

    with pytest.raises(ValueError):
        WatchTarget(type="author", ror="03yrm5c26")


def test_resolve_targets_uses_external_ids_and_fills_missing_names() -> None:
    watchlist = WatchlistConfig.model_validate(
        {
            "targets": [
                {"type": "author", "orcid": "0000-0001-2345-6789"},
                {"type": "institution", "ror": "https://ror.org/03yrm5c26"},
                {"type": "author", "openalex_id": "A123"},
                {"type": "institution", "openalex_id": "I456", "name": "Alias"},
            ]
        }
    )

    resolved = resolve_targets(watchlist, FakeOpenAlexClient())

    assert [target.name for target in resolved] == [
        "ORCID Author",
        "ROR Institution",
        "Fetched Author",
        "Alias",
    ]
    assert [target.openalex_id for target in resolved] == [
        "https://openalex.org/A999",
        "https://openalex.org/I999",
        "https://openalex.org/A123",
        "https://openalex.org/I456",
    ]


def test_resolve_topic_fields_uses_openalex_ids_and_names() -> None:
    watchlist = WatchlistConfig.model_validate(
        {
            "targets": [{"type": "author", "name": "Yann LeCun"}],
            "topic_filters": {
                "fields": [
                    {"openalex_id": "17"},
                    {"name": "Physics"},
                ]
            },
        }
    )

    resolved = resolve_topic_fields(watchlist, FakeOpenAlexClient())

    assert [field.name for field in resolved] == ["Computer Science", "Physics"]
    assert [field.openalex_id for field in resolved] == [
        "https://openalex.org/fields/17",
        "https://openalex.org/fields/31",
    ]
