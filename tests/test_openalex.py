from __future__ import annotations

from datetime import date
from typing import Any

import httpx

from openalex_paper_bot.openalex import OpenAlexClient


class RecordingOpenAlexClient(OpenAlexClient):
    def __init__(self) -> None:
        super().__init__("test-key")
        self.requests: list[dict[str, Any]] = []

    def _request_json(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        self.requests.append({"method": method, "path": path, "params": params or {}})
        return {"results": [], "meta": {"next_cursor": None}}


def test_author_and_institution_fetches_use_configured_work_types() -> None:
    client = RecordingOpenAlexClient()
    try:
        client.fetch_recent_works_for_author(
            "https://openalex.org/A123",
            date(2026, 3, 31),
            work_types=["article", "preprint"],
            topic_filters=["primary_topic.field.id:17|31"],
        )
        client.fetch_recent_works_for_institution(
            "https://openalex.org/I4210090411",
            date(2026, 3, 31),
            work_types=["article", "preprint"],
            topic_filters=["primary_topic.field.id:17|31"],
        )
    finally:
        client.close()

    assert len(client.requests) == 2
    assert client.requests[0]["params"]["filter"] == (
        "authorships.author.id:A123,type:article|preprint,primary_topic.field.id:17|31,from_publication_date:2026-03-31"
    )
    assert client.requests[1]["params"]["filter"] == (
        "authorships.institutions.id:I4210090411,"
        "type:article|preprint,"
        "primary_topic.field.id:17|31,"
        "from_publication_date:2026-03-31"
    )
    assert "abstract_inverted_index" in client.requests[0]["params"]["select"]
    assert "abstract_inverted_index" in client.requests[1]["params"]["select"]


def test_query_fetch_uses_configured_work_types_for_search_and_filtered_search() -> None:
    client = RecordingOpenAlexClient()
    try:
        client.fetch_recent_works_for_query(
            "world model",
            date(2026, 3, 31),
            field="search",
            work_types=["article"],
            topic_filters=["topics.field.id:17"],
        )
        client.fetch_recent_works_for_query(
            "multimodal agents",
            date(2026, 3, 31),
            field="title_and_abstract",
            work_types=["preprint"],
            topic_filters=["topics.field.id:31"],
        )
    finally:
        client.close()

    assert len(client.requests) == 2
    assert client.requests[0]["params"]["search"] == "world model"
    assert client.requests[0]["params"]["filter"] == (
        "type:article,topics.field.id:17,from_publication_date:2026-03-31"
    )
    assert client.requests[1]["params"]["filter"] == (
        "title_and_abstract.search:multimodal agents,type:preprint,topics.field.id:31,from_publication_date:2026-03-31"
    )


def test_topic_field_filters_support_primary_and_any_topic_matching() -> None:
    client = RecordingOpenAlexClient()
    try:
        assert client.topic_field_filters(
            ["https://openalex.org/fields/17", "31"],
            match_mode="primary",
        ) == ["primary_topic.field.id:17|31"]
        assert client.topic_field_filters(
            ["https://openalex.org/fields/17"],
            match_mode="any_topic",
        ) == ["topics.field.id:17"]
    finally:
        client.close()


def test_paper_from_work_reconstructs_abstract_from_inverted_index() -> None:
    paper = OpenAlexClient._paper_from_work(
        {
            "id": "https://openalex.org/W1",
            "title": "Useful paper",
            "publication_date": "2026-04-03",
            "doi": None,
            "authorships": [{"author": {"display_name": "Alice"}}],
            "primary_location": {"landing_page_url": "https://example.com/paper"},
            "abstract_inverted_index": {
                "This": [0],
                "paper": [1],
                "summarizes": [2],
                "abstracts.": [3],
            },
        }
    )

    assert paper.abstract == "This paper summarizes abstracts."


def test_paper_from_work_uses_none_for_missing_abstract() -> None:
    paper = OpenAlexClient._paper_from_work(
        {
            "id": "https://openalex.org/W1",
            "title": "Useful paper",
            "publication_date": "2026-04-03",
            "doi": None,
            "authorships": [],
            "primary_location": {"landing_page_url": "https://example.com/paper"},
            "abstract_inverted_index": None,
        }
    )

    assert paper.abstract is None


def test_fetch_fills_missing_abstract_from_crossref() -> None:
    crossref_requests: list[httpx.Request] = []

    def crossref_handler(request: httpx.Request) -> httpx.Response:
        crossref_requests.append(request)
        return httpx.Response(
            200,
            json={
                "message": {
                    "abstract": "<jats:p>Crossref <jats:italic>abstract</jats:italic> text.</jats:p>",
                }
            },
        )

    class CrossrefFallbackClient(OpenAlexClient):
        def _request_json(
            self,
            method: str,
            path: str,
            *,
            params: dict[str, Any] | None = None,
        ) -> dict[str, Any]:
            return {
                "results": [
                    {
                        "id": "https://openalex.org/W1",
                        "title": "Useful paper",
                        "publication_date": "2026-04-03",
                        "doi": "https://doi.org/10.1000/example",
                        "authorships": [],
                        "primary_location": {"landing_page_url": "https://example.com/paper"},
                        "abstract_inverted_index": None,
                    }
                ],
                "meta": {"next_cursor": None},
            }

    crossref_client = httpx.Client(
        base_url="https://api.crossref.org",
        transport=httpx.MockTransport(crossref_handler),
    )
    client = CrossrefFallbackClient("test-key", crossref_client=crossref_client)
    try:
        papers = client.fetch_recent_works_for_query(
            "useful",
            date(2026, 3, 31),
            work_types=["article"],
        )
    finally:
        client.close()

    assert papers[0].abstract == "Crossref abstract text."
    assert [request.url.raw_path for request in crossref_requests] == [b"/works/10.1000%2Fexample"]


def test_fetch_keeps_openalex_abstract_without_crossref_lookup() -> None:
    def crossref_handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("Crossref should not be queried when OpenAlex has an abstract.")

    class OpenAlexAbstractClient(OpenAlexClient):
        def _request_json(
            self,
            method: str,
            path: str,
            *,
            params: dict[str, Any] | None = None,
        ) -> dict[str, Any]:
            return {
                "results": [
                    {
                        "id": "https://openalex.org/W1",
                        "title": "Useful paper",
                        "publication_date": "2026-04-03",
                        "doi": "https://doi.org/10.1000/example",
                        "authorships": [],
                        "primary_location": {"landing_page_url": "https://example.com/paper"},
                        "abstract_inverted_index": {"OpenAlex": [0], "abstract.": [1]},
                    }
                ],
                "meta": {"next_cursor": None},
            }

    crossref_client = httpx.Client(
        base_url="https://api.crossref.org",
        transport=httpx.MockTransport(crossref_handler),
    )
    client = OpenAlexAbstractClient("test-key", crossref_client=crossref_client)
    try:
        papers = client.fetch_recent_works_for_query(
            "useful",
            date(2026, 3, 31),
            work_types=["article"],
        )
    finally:
        client.close()

    assert papers[0].abstract == "OpenAlex abstract."


def test_fetch_leaves_abstract_missing_when_crossref_has_none() -> None:
    def crossref_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"message": {}})

    class MissingAbstractClient(OpenAlexClient):
        def _request_json(
            self,
            method: str,
            path: str,
            *,
            params: dict[str, Any] | None = None,
        ) -> dict[str, Any]:
            return {
                "results": [
                    {
                        "id": "https://openalex.org/W1",
                        "title": "Useful paper",
                        "publication_date": "2026-04-03",
                        "doi": "https://doi.org/10.1000/example",
                        "authorships": [],
                        "primary_location": {"landing_page_url": "https://example.com/paper"},
                        "abstract_inverted_index": None,
                    }
                ],
                "meta": {"next_cursor": None},
            }

    crossref_client = httpx.Client(
        base_url="https://api.crossref.org",
        transport=httpx.MockTransport(crossref_handler),
    )
    client = MissingAbstractClient("test-key", crossref_client=crossref_client)
    try:
        papers = client.fetch_recent_works_for_query(
            "useful",
            date(2026, 3, 31),
            work_types=["article"],
        )
    finally:
        client.close()

    assert papers[0].abstract is None
