from __future__ import annotations

from datetime import date
from pathlib import Path

from openalex_paper_bot.models import (
    GlobalQueryField,
    Paper,
    ResolvedTarget,
    ResolvedTopicField,
    RuntimeConfig,
    TopicMatchMode,
    WatchlistConfig,
    WorkType,
)
from openalex_paper_bot.runner import (
    collapse_equivalent_papers,
    drop_previously_sent,
    fetch_papers,
    render_watchlist_yaml,
)


class FakeDiscoveryClient:
    def topic_field_filters(
        self,
        field_ids: list[str],
        *,
        match_mode: TopicMatchMode,
    ) -> list[str]:
        assert field_ids == ["https://openalex.org/fields/17"]
        assert match_mode == "primary"
        return ["primary_topic.field.id:17"]

    def fetch_recent_works_for_author(
        self,
        author_id: str,
        from_date: date,
        *,
        work_types: list[WorkType],
        topic_filters: list[str] | None = None,
    ) -> list[Paper]:
        assert author_id == "https://openalex.org/A123"
        assert from_date == date(2026, 4, 1)
        assert work_types == ["article", "preprint"]
        assert topic_filters == ["primary_topic.field.id:17"]
        return [
            Paper(
                work_id="https://openalex.org/W1",
                title="Target paper",
                publication_date=date(2026, 4, 3),
                landing_url="https://example.com/w1",
                authors_summary="Alice",
            )
        ]

    def fetch_recent_works_for_institution(
        self,
        inst_id: str,
        from_date: date,
        *,
        work_types: list[WorkType],
        topic_filters: list[str] | None = None,
    ) -> list[Paper]:
        raise AssertionError("Institution fetch should not be called in this test.")

    def fetch_recent_works_for_query(
        self,
        query: str,
        from_date: date,
        *,
        field: GlobalQueryField = "title_and_abstract",
        work_types: list[WorkType],
        topic_filters: list[str] | None = None,
    ) -> list[Paper]:
        assert query == "world model"
        assert field == "title_and_abstract"
        assert from_date == date(2026, 4, 1)
        assert work_types == ["article", "preprint"]
        assert topic_filters == ["primary_topic.field.id:17"]
        return [
            Paper(
                work_id="https://openalex.org/W1",
                title="Target paper",
                publication_date=date(2026, 4, 3),
                landing_url="https://example.com/w1",
                authors_summary="Alice",
            ),
            Paper(
                work_id="https://openalex.org/W2",
                title="Expanded paper",
                publication_date=date(2026, 4, 2),
                landing_url="https://example.com/w2",
                authors_summary="Bob",
            ),
        ]


def test_fetch_papers_merges_target_and_global_query_results() -> None:
    watchlist = WatchlistConfig.model_validate(
        {
            "topic_filters": {
                "match_mode": "primary",
                "fields": [{"name": "Computer Science", "openalex_id": "17"}],
            },
            "targets": [{"type": "author", "name": "Yann LeCun", "openalex_id": "A123"}],
            "global_queries": [{"query": "world model"}],
        }
    )
    config = RuntimeConfig(
        project_root=Path("."),
        watchlist_path=Path("watchlist.yaml"),
        state_path=Path("data/state.json"),
        watchlist=watchlist,
    )
    resolved_targets = [
        ResolvedTarget(
            type="author",
            name="Yann LeCun",
            openalex_id="https://openalex.org/A123",
            resolved_name="Yann LeCun",
        )
    ]

    papers = fetch_papers(
        config,
        resolved_targets,
        [
            ResolvedTopicField(
                name="Computer Science",
                openalex_id="https://openalex.org/fields/17",
                resolved_name="Computer Science",
            )
        ],
        FakeDiscoveryClient(),
        from_date=date(2026, 4, 1),
    )

    assert [paper.work_id for paper in papers] == [
        "https://openalex.org/W1",
        "https://openalex.org/W2",
    ]
    assert papers[0].matched_targets == ["Yann LeCun", "Query: world model"]
    assert papers[1].matched_targets == ["Query: world model"]


def test_watchlist_global_query_defaults_and_labels() -> None:
    watchlist = WatchlistConfig.model_validate(
        {
            "targets": [{"type": "author", "name": "Yann LeCun"}],
            "topic_filters": {"fields": [{"name": "Computer Science"}]},
            "global_queries": [
                {"query": "graph learning"},
                {"query": "agents", "label": "Custom query", "field": "search"},
            ],
        }
    )

    assert watchlist.global_queries[0].field == "title_and_abstract"
    assert watchlist.global_queries[0].display_label() == "Query: graph learning"
    assert watchlist.global_queries[1].field == "search"
    assert watchlist.global_queries[1].display_label() == "Custom query"
    assert watchlist.work_types == ["article", "preprint"]
    assert watchlist.topic_filters.match_mode == "primary"


def test_collapse_equivalent_papers_prefers_doi_record_and_keeps_all_source_ids() -> None:
    papers = [
        Paper(
            work_id="https://openalex.org/W1",
            title="World Models for Something",
            publication_date=date(2026, 4, 3),
            landing_url="https://arxiv.org/abs/1234.5678",
            abstract="This record has the only abstract.",
            authors_summary="Alice, Bob",
            lead_author="Alice",
            matched_targets=["Meta"],
            source_work_ids=["https://openalex.org/W1"],
        ),
        Paper(
            work_id="https://openalex.org/W2",
            title="World Models for Something",
            publication_date=date(2026, 4, 5),
            doi="10.1000/example",
            landing_url="https://doi.org/10.1000/example",
            authors_summary="Alice, Bob",
            lead_author="Alice",
            matched_targets=["Yann LeCun"],
            source_work_ids=["https://openalex.org/W2"],
        ),
    ]

    collapsed = collapse_equivalent_papers(papers)

    assert len(collapsed) == 1
    assert collapsed[0].work_id == "https://openalex.org/W2"
    assert collapsed[0].landing_url == "https://doi.org/10.1000/example"
    assert collapsed[0].matched_targets == ["Yann LeCun", "Meta"]
    assert collapsed[0].source_work_ids == [
        "https://openalex.org/W2",
        "https://openalex.org/W1",
    ]
    assert collapsed[0].abstract == "This record has the only abstract."


def test_drop_previously_sent_uses_signatures_as_well_as_work_ids() -> None:
    papers = [
        Paper(
            work_id="https://openalex.org/W9",
            title="World Models for Something",
            publication_date=date(2026, 4, 5),
            doi="10.1000/example",
            landing_url="https://doi.org/10.1000/example",
            authors_summary="Alice, Bob",
            lead_author="Alice",
        )
    ]

    filtered = drop_previously_sent(
        papers,
        sent_work_ids=[],
        sent_paper_signatures=["title:world models for something|lead:alice"],
    )

    assert filtered == []


def test_render_watchlist_yaml_keeps_top_level_spacing_and_indented_lists() -> None:
    rendered = render_watchlist_yaml(
        {
            "lookback_days": 2,
            "work_types": ["article", "preprint"],
            "topic_filters": {
                "match_mode": "primary",
                "fields": [{"name": "Computer Science", "openalex_id": "https://openalex.org/fields/17"}],
            },
            "targets": [{"type": "author", "name": "Yann LeCun"}],
        }
    )

    assert "lookback_days: 2\n\nwork_types:\n  - article\n  - preprint\n\ntopic_filters:" in rendered
    assert "\n\ntargets:\n  - type: author\n    name: Yann LeCun\n" in rendered
