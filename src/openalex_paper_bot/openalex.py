"""Resolve OpenAlex entities and fetch normalized work records.

This module wraps the OpenAlex REST API for the limited set of operations the
bot needs: resolving stable IDs, building filtered work queries, paging through
results, and normalizing responses into internal ``Paper`` objects.
"""

from __future__ import annotations

import time
from datetime import date
from typing import Any, cast

import httpx

from openalex_paper_bot.models import EntityRef, EntityType, GlobalQueryField, Paper, TopicMatchMode, WorkType

BASE_URL = "https://api.openalex.org"
OPENALEX_ID_PREFIX = "https://openalex.org/"
ORCID_ID_PREFIX = "https://orcid.org/"
ROR_ID_PREFIX = "https://ror.org/"
DOI_URL_PREFIX = "https://doi.org/"
FIELD_ID_PREFIX = "https://openalex.org/fields/"


def normalize_openalex_id(raw_id: str, *, expected_prefix: str | None = None) -> str:
    """Normalize a raw OpenAlex ID into the canonical URL form.

    Args:
        raw_id: Raw OpenAlex identifier in key, URL, or API path form.
        expected_prefix: Optional leading key prefix such as ``A`` or ``I``.

    Returns:
        The canonical ``https://openalex.org/...`` identifier.

    Raises:
        ValueError: If the identifier is empty or has the wrong prefix.

    """
    value = raw_id.strip()
    if not value:
        raise ValueError("OpenAlex ID cannot be empty.")
    if "/authors/" in value or "/institutions/" in value or "/works/" in value:
        value = value.rstrip("/").split("/")[-1]
    key = value[len(OPENALEX_ID_PREFIX) :] if value.startswith(OPENALEX_ID_PREFIX) else value
    key = key.upper()
    if expected_prefix and not key.startswith(expected_prefix.upper()):
        raise ValueError(f"Expected an OpenAlex ID starting with {expected_prefix}: {raw_id}")
    return f"{OPENALEX_ID_PREFIX}{key}"


def openalex_key(raw_id: str, *, expected_prefix: str | None = None) -> str:
    """Return only the compact OpenAlex key.

    Args:
        raw_id: Raw OpenAlex identifier in key or URL form.
        expected_prefix: Optional leading key prefix such as ``A`` or ``I``.

    Returns:
        The compact OpenAlex key without the URL prefix.

    """
    return normalize_openalex_id(raw_id, expected_prefix=expected_prefix).removeprefix(OPENALEX_ID_PREFIX)


def normalize_orcid(raw_id: str) -> str:
    """Normalize an ORCID into canonical URL form.

    Args:
        raw_id: ORCID in bare or URL form.

    Returns:
        The canonical ``https://orcid.org/...`` representation.

    Raises:
        ValueError: If the ORCID is empty or malformed.

    """
    value = raw_id.strip()
    if not value:
        raise ValueError("ORCID cannot be empty.")
    if value.startswith(ORCID_ID_PREFIX):
        value = value[len(ORCID_ID_PREFIX) :]
    value = value.replace("-", "").upper()
    if len(value) != 16 or not all(char.isdigit() or char == "X" for char in value):
        raise ValueError(f"Invalid ORCID: {raw_id}")
    chunks = [value[index : index + 4] for index in range(0, 16, 4)]
    return f"{ORCID_ID_PREFIX}{'-'.join(chunks)}"


def normalize_ror(raw_id: str) -> str:
    """Normalize a ROR ID into canonical URL form.

    Args:
        raw_id: ROR identifier in bare or URL form.

    Returns:
        The canonical ``https://ror.org/...`` representation.

    Raises:
        ValueError: If the ROR is empty or malformed.

    """
    value = raw_id.strip()
    if not value:
        raise ValueError("ROR cannot be empty.")
    if value.startswith(ROR_ID_PREFIX):
        value = value[len(ROR_ID_PREFIX) :]
    value = value.lower().strip("/")
    if len(value) != 9 or not value.isalnum():
        raise ValueError(f"Invalid ROR: {raw_id}")
    return f"{ROR_ID_PREFIX}{value}"


def normalize_doi(raw_doi: str) -> str:
    """Normalize a DOI into canonical lower-case form without the URL prefix.

    Args:
        raw_doi: DOI in bare or URL form.

    Returns:
        The DOI without the ``https://doi.org/`` prefix.

    Raises:
        ValueError: If the DOI is empty.

    """
    value = raw_doi.strip()
    if not value:
        raise ValueError("DOI cannot be empty.")
    if value.lower().startswith(DOI_URL_PREFIX):
        value = value[len(DOI_URL_PREFIX) :]
    return value.strip().lower()


def normalize_field_id(raw_id: str) -> str:
    """Normalize an OpenAlex field ID into canonical URL form.

    Args:
        raw_id: Field identifier in numeric or URL form.

    Returns:
        The canonical ``https://openalex.org/fields/...`` identifier.

    Raises:
        ValueError: If the identifier is empty or malformed.

    """
    value = raw_id.strip()
    if not value:
        raise ValueError("Field ID cannot be empty.")
    if "/fields/" in value:
        value = value.rstrip("/").split("/")[-1]
    suffix = value[len(FIELD_ID_PREFIX) :] if value.startswith(FIELD_ID_PREFIX) else value
    if not suffix.isdigit():
        raise ValueError(f"Invalid OpenAlex field ID: {raw_id}")
    return f"{FIELD_ID_PREFIX}{suffix}"


def field_key(raw_id: str) -> str:
    """Return the compact numeric OpenAlex field key.

    Args:
        raw_id: Field identifier in numeric or URL form.

    Returns:
        The numeric field key without the URL prefix.

    """
    return normalize_field_id(raw_id).removeprefix(FIELD_ID_PREFIX)


class OpenAlexClient:
    """Resolve OpenAlex entities and fetch normalized recent works."""

    def __init__(self, api_key: str, *, timeout: float = 20.0) -> None:
        """Initialize the OpenAlex client.

        Args:
            api_key: OpenAlex API key used for all requests.
            timeout: Request timeout in seconds.

        """
        self.api_key = api_key
        self._client = httpx.Client(
            base_url=BASE_URL,
            timeout=timeout,
            headers={"User-Agent": "openalex-paper-bot/0.1.0"},
        )

    def __enter__(self) -> OpenAlexClient:
        """Return the client for ``with`` statement usage."""
        return self

    def __exit__(self, *_: object) -> None:
        """Close the client when leaving a context manager."""
        self.close()

    def close(self) -> None:
        """Close the underlying HTTP client."""
        self._client.close()

    def resolve_author(self, name: str) -> EntityRef:
        """Resolve an author name to a stable OpenAlex ID.

        Args:
            name: Display name to search for.

        Returns:
            The best matching author reference.

        """
        return self._resolve_entity("authors", name, entity_type="author")

    def get_author(self, author_id: str) -> EntityRef:
        """Fetch a single author by OpenAlex ID.

        Args:
            author_id: Author OpenAlex ID in key or URL form.

        Returns:
            The resolved author reference.

        """
        return self._get_entity("authors", author_id, expected_prefix="A", entity_type="author")

    def resolve_author_by_orcid(self, orcid: str) -> EntityRef:
        """Resolve an author ORCID to a stable OpenAlex ID.

        Args:
            orcid: ORCID in bare or URL form.

        Returns:
            The resolved author reference.

        """
        return self._resolve_entity_by_filter(
            "authors",
            entity_type="author",
            filter_field="orcid",
            filter_value=normalize_orcid(orcid),
        )

    def resolve_institution(self, name: str) -> EntityRef:
        """Resolve an institution name to a stable OpenAlex ID.

        Args:
            name: Display name to search for.

        Returns:
            The best matching institution reference.

        """
        return self._resolve_entity("institutions", name, entity_type="institution")

    def get_institution(self, inst_id: str) -> EntityRef:
        """Fetch a single institution by OpenAlex ID.

        Args:
            inst_id: Institution OpenAlex ID in key or URL form.

        Returns:
            The resolved institution reference.

        """
        return self._get_entity(
            "institutions",
            inst_id,
            expected_prefix="I",
            entity_type="institution",
        )

    def resolve_institution_by_ror(self, ror: str) -> EntityRef:
        """Resolve an institution ROR to a stable OpenAlex ID.

        Args:
            ror: ROR in bare or URL form.

        Returns:
            The resolved institution reference.

        """
        return self._resolve_entity_by_filter(
            "institutions",
            entity_type="institution",
            filter_field="ror",
            filter_value=normalize_ror(ror),
        )

    def resolve_field(self, name: str) -> EntityRef:
        """Resolve a field name to a stable OpenAlex field ID.

        Args:
            name: Broad field display name to search for.

        Returns:
            The resolved field reference.

        """
        return self._resolve_field_entity(name)

    def get_field(self, field_id: str) -> EntityRef:
        """Fetch a single field by OpenAlex field ID.

        Args:
            field_id: Field OpenAlex ID in numeric or URL form.

        Returns:
            The resolved field reference.

        """
        return self._get_field_entity(field_id)

    def fetch_recent_works_for_author(
        self,
        author_id: str,
        from_date: date,
        *,
        work_types: list[WorkType],
        topic_filters: list[str] | None = None,
    ) -> list[Paper]:
        """Fetch recent works matching an author OpenAlex ID.

        Args:
            author_id: Author OpenAlex ID in key or URL form.
            from_date: Inclusive publication date lower bound.
            work_types: Allowed OpenAlex work types.
            topic_filters: Optional precomputed OpenAlex topic filters.

        Returns:
            A list of normalized papers returned by OpenAlex.

        """
        author_key = openalex_key(author_id, expected_prefix="A")
        return self._fetch_recent_works(
            entity_filters=[
                f"authorships.author.id:{author_key}",
                self._work_types_filter(work_types),
                *(topic_filters or []),
            ],
            from_date=from_date,
        )

    def fetch_recent_works_for_institution(
        self,
        inst_id: str,
        from_date: date,
        *,
        work_types: list[WorkType],
        topic_filters: list[str] | None = None,
    ) -> list[Paper]:
        """Fetch recent works matching an institution OpenAlex ID.

        Args:
            inst_id: Institution OpenAlex ID in key or URL form.
            from_date: Inclusive publication date lower bound.
            work_types: Allowed OpenAlex work types.
            topic_filters: Optional precomputed OpenAlex topic filters.

        Returns:
            A list of normalized papers returned by OpenAlex.

        """
        institution_key = openalex_key(inst_id, expected_prefix="I")
        return self._fetch_recent_works(
            entity_filters=[
                f"authorships.institutions.id:{institution_key}",
                self._work_types_filter(work_types),
                *(topic_filters or []),
            ],
            from_date=from_date,
        )

    def fetch_recent_works_for_query(
        self,
        query: str,
        from_date: date,
        *,
        field: GlobalQueryField = "title_and_abstract",
        work_types: list[WorkType],
        topic_filters: list[str] | None = None,
    ) -> list[Paper]:
        """Fetch recent works matching a global keyword query.

        Args:
            query: Keyword query string.
            from_date: Inclusive publication date lower bound.
            field: OpenAlex search field to query against.
            work_types: Allowed OpenAlex work types.
            topic_filters: Optional precomputed OpenAlex topic filters.

        Returns:
            A list of normalized papers returned by OpenAlex.

        """
        filters = [self._work_types_filter(work_types), *(topic_filters or [])]
        if field == "search":
            params = self._works_params(from_date, extra_filters=filters)
            params["search"] = query
        else:
            filter_field = {
                "title": "title.search",
                "abstract": "abstract.search",
                "title_and_abstract": "title_and_abstract.search",
            }[field]
            params = self._works_params(
                from_date,
                extra_filters=[f"{filter_field}:{query}", *filters],
            )
        return self._fetch_recent_works(params=params)

    def _resolve_field_entity(self, name: str) -> EntityRef:
        """Resolve a field search string via the OpenAlex fields endpoint."""
        payload = self._request_json(
            "GET",
            "/fields",
            params={
                "api_key": self.api_key,
                "search": name,
                "per_page": 5,
                "select": "id,display_name,works_count",
            },
        )
        results = payload.get("results", [])
        if not results:
            raise ValueError(f"No OpenAlex field match found for {name!r}.")

        best = self._pick_best_search_result(name, results)
        return EntityRef(
            entity_type="field",
            openalex_id=normalize_field_id(best["id"]),
            display_name=best.get("display_name") or name,
        )

    def _get_field_entity(self, field_id: str) -> EntityRef:
        """Fetch a single field record from the OpenAlex fields endpoint."""
        field_id_key = field_key(field_id)
        payload = self._request_json(
            "GET",
            f"/fields/{field_id_key}",
            params={"api_key": self.api_key},
        )
        return EntityRef(
            entity_type="field",
            openalex_id=normalize_field_id(payload["id"]),
            display_name=payload.get("display_name") or field_id_key,
        )

    def _resolve_entity(self, endpoint: str, name: str, *, entity_type: EntityType) -> EntityRef:
        """Resolve an entity name against a list endpoint."""
        payload = self._request_json(
            "GET",
            f"/{endpoint}",
            params={
                "api_key": self.api_key,
                "search": name,
                "per_page": 5,
                "select": "id,display_name,works_count",
            },
        )
        results = payload.get("results", [])
        if not results:
            raise ValueError(f"No OpenAlex {entity_type} match found for {name!r}.")

        best = self._pick_best_search_result(name, results)
        return EntityRef(
            entity_type=entity_type,
            openalex_id=normalize_openalex_id(best["id"]),
            display_name=best.get("display_name") or name,
        )

    def _resolve_entity_by_filter(
        self,
        endpoint: str,
        *,
        entity_type: EntityType,
        filter_field: str,
        filter_value: str,
    ) -> EntityRef:
        """Resolve an entity by a stable external identifier filter."""
        payload = self._request_json(
            "GET",
            f"/{endpoint}",
            params={
                "api_key": self.api_key,
                "filter": f"{filter_field}:{filter_value}",
                "per_page": 2,
                "select": "id,display_name,works_count",
            },
        )
        results = payload.get("results", [])
        if not results:
            raise ValueError(f"No OpenAlex {entity_type} match found for {filter_field}={filter_value!r}.")
        best = results[0]
        return EntityRef(
            entity_type=entity_type,
            openalex_id=normalize_openalex_id(best["id"]),
            display_name=best.get("display_name") or filter_value,
        )

    def _get_entity(
        self,
        endpoint: str,
        entity_id: str,
        *,
        expected_prefix: str,
        entity_type: EntityType,
    ) -> EntityRef:
        """Fetch a single entity from an OpenAlex detail endpoint."""
        entity_key = openalex_key(entity_id, expected_prefix=expected_prefix)
        payload = self._request_json(
            "GET",
            f"/{endpoint}/{entity_key}",
            params={"api_key": self.api_key},
        )
        return EntityRef(
            entity_type=entity_type,
            openalex_id=normalize_openalex_id(payload["id"], expected_prefix=expected_prefix),
            display_name=payload.get("display_name") or entity_key,
        )

    def _fetch_recent_works(
        self,
        *,
        params: dict[str, Any] | None = None,
        entity_filters: list[str] | None = None,
        from_date: date | None = None,
    ) -> list[Paper]:
        """Fetch paginated work results and normalize them into ``Paper`` objects.

        Args:
            params: Optional prebuilt request parameters.
            entity_filters: Optional list of filters combined into the query.
            from_date: Inclusive publication date lower bound for entity-based
                fetches.

        Returns:
            A list of normalized papers.

        """
        papers: list[Paper] = []
        cursor: str | None = "*"
        request_params = dict(params or {})
        if entity_filters is not None:
            if from_date is None:
                raise ValueError("from_date is required when entity_filters are provided.")
            request_params = self._works_params(from_date, extra_filters=entity_filters)

        while cursor:
            payload = self._request_json(
                "GET",
                "/works",
                params={
                    **request_params,
                    "cursor": cursor,
                },
            )
            results = payload.get("results", [])
            papers.extend(self._paper_from_work(item) for item in results)
            raw_cursor = (payload.get("meta") or {}).get("next_cursor")
            cursor = raw_cursor if isinstance(raw_cursor, str) else None
            if not results:
                break

        return papers

    def _works_params(
        self,
        from_date: date,
        *,
        extra_filters: list[str] | None = None,
    ) -> dict[str, Any]:
        """Return common parameters used for work discovery requests.

        Args:
            from_date: Inclusive publication date lower bound.
            extra_filters: Additional OpenAlex filters to append.

        Returns:
            A request-parameter mapping for the works endpoint.

        """
        filters = [*(extra_filters or []), f"from_publication_date:{from_date.isoformat()}"]
        return {
            "api_key": self.api_key,
            "filter": ",".join(filters),
            "sort": "publication_date:desc",
            "per_page": 100,
            "select": (
                "id,title,publication_date,doi,authorships,primary_location,best_oa_location,abstract_inverted_index"
            ),
        }

    @staticmethod
    def _work_types_filter(work_types: list[WorkType]) -> str:
        """Return an OpenAlex OR filter for configured work types.

        Args:
            work_types: Allowed work types.

        Returns:
            An OpenAlex ``type:...`` filter expression.

        """
        return "type:" + "|".join(work_types)

    @staticmethod
    def topic_field_filters(field_ids: list[str], *, match_mode: TopicMatchMode) -> list[str]:
        """Return OpenAlex filters for broad field-based topic matching.

        Args:
            field_ids: Resolved OpenAlex field IDs.
            match_mode: Whether to match only the primary topic field or any
                assigned topic field.

        Returns:
            Zero or one OpenAlex field filter expressions.

        """
        if not field_ids:
            return []
        keys = "|".join(field_key(field_id) for field_id in field_ids)
        filter_field = "primary_topic.field.id" if match_mode == "primary" else "topics.field.id"
        return [f"{filter_field}:{keys}"]

    def _request_json(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Execute an OpenAlex request with retries and JSON parsing.

        Args:
            method: HTTP method.
            path: OpenAlex API path.
            params: Optional query parameters.

        Returns:
            The decoded JSON response body.

        Raises:
            RuntimeError: If the request fails after all retry attempts.

        """
        last_error: Exception | None = None
        for attempt in range(1, 4):
            try:
                response = self._client.request(method, path, params=params)
                if response.status_code in {429, 500, 502, 503, 504} and attempt < 3:
                    time.sleep(0.5 * attempt)
                    continue
                response.raise_for_status()
                return cast(dict[str, Any], response.json())
            except (httpx.HTTPError, ValueError) as exc:
                last_error = exc
                if attempt < 3:
                    time.sleep(0.5 * attempt)
                    continue

        raise RuntimeError(f"OpenAlex request failed for {path}: {last_error}") from last_error

    @staticmethod
    def _pick_best_search_result(name: str, results: list[dict[str, Any]]) -> dict[str, Any]:
        """Choose the best OpenAlex search result for a display name."""
        name_folded = name.casefold()
        for result in results:
            display_name = (result.get("display_name") or "").casefold()
            if display_name == name_folded:
                return result
        return max(results, key=lambda item: int(item.get("works_count") or 0))

    @staticmethod
    def _paper_from_work(work: dict[str, Any]) -> Paper:
        """Normalize a raw OpenAlex work payload into a ``Paper``."""
        publication_date = work.get("publication_date")
        title = (work.get("title") or "Untitled").strip() or "Untitled"
        work_id = normalize_openalex_id(work["id"], expected_prefix="W")
        authorships = work.get("authorships") or []
        authors_summary = OpenAlexClient._authors_summary(authorships)
        doi = work.get("doi")
        return Paper(
            work_id=work_id,
            title=title,
            publication_date=publication_date,
            doi=normalize_doi(doi) if doi else None,
            landing_url=OpenAlexClient._best_landing_url(work),
            abstract=OpenAlexClient._abstract_from_inverted_index(work.get("abstract_inverted_index")),
            authors_summary=authors_summary,
            lead_author=OpenAlexClient._lead_author(authorships),
            source_work_ids=[work_id],
        )

    @staticmethod
    def _abstract_from_inverted_index(raw_index: object) -> str | None:
        """Reconstruct plain abstract text from OpenAlex's inverted index."""
        if not isinstance(raw_index, dict):
            return None

        tokens_by_position: dict[int, str] = {}
        for raw_token, raw_positions in raw_index.items():
            if not isinstance(raw_token, str) or not isinstance(raw_positions, list):
                continue
            for raw_position in raw_positions:
                if isinstance(raw_position, int) and raw_position >= 0:
                    tokens_by_position[raw_position] = raw_token

        if not tokens_by_position:
            return None
        return " ".join(tokens_by_position[position] for position in sorted(tokens_by_position))

    @staticmethod
    def _authors_summary(authorships: list[dict[str, Any]]) -> str:
        """Summarize authorship names for compact digest output."""
        names = [authorship.get("author", {}).get("display_name", "").strip() for authorship in authorships]
        names = [name for name in names if name]
        if not names:
            return "Unknown authors"
        if len(names) <= 3:
            return ", ".join(names)
        return f"{', '.join(names[:3])}, et al."

    @staticmethod
    def _lead_author(authorships: list[dict[str, Any]]) -> str | None:
        """Return the first listed author name when available.

        Args:
            authorships: Raw OpenAlex authorship entries.

        Returns:
            The first author display name, or ``None`` when unavailable.

        """
        for authorship in authorships:
            raw_name = authorship.get("author", {}).get("display_name", "")
            name = raw_name if isinstance(raw_name, str) else ""
            name = name.strip()
            if name:
                return name
        return None

    @staticmethod
    def _best_landing_url(work: dict[str, Any]) -> str:
        """Choose the most useful landing URL for a normalized paper."""
        for field in ("primary_location", "best_oa_location"):
            location = work.get(field) or {}
            raw_landing_page_url = location.get("landing_page_url")
            landing_page_url = raw_landing_page_url if isinstance(raw_landing_page_url, str) else None
            if landing_page_url:
                return landing_page_url
        raw_doi = work.get("doi")
        if isinstance(raw_doi, str) and raw_doi:
            return raw_doi
        return normalize_openalex_id(work["id"], expected_prefix="W")
