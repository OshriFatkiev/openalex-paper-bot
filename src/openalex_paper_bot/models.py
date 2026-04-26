"""Define the validated data models shared across the paper bot.

These Pydantic models describe the watchlist schema, persisted state, resolved
OpenAlex entities, normalized papers, and runtime summaries passed between
modules.
"""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

TargetType = Literal["author", "institution"]
EntityType = Literal["author", "institution", "field"]
GlobalQueryField = Literal["search", "title", "abstract", "title_and_abstract"]
WorkType = Literal["article", "preprint"]
TopicMatchMode = Literal["primary", "any_topic"]
SummaryProvider = Literal["fake"]


class WatchTarget(BaseModel):
    """A watchlist entry for an author or institution.

    Attributes:
        type: Whether the target is an author or institution.
        name: Optional human-readable name used in digests and YAML.
        openalex_id: Stable OpenAlex ID when already known.
        orcid: Optional ORCID for author targets.
        ror: Optional ROR for institution targets.

    """

    type: TargetType
    name: str | None = None
    openalex_id: str | None = None
    orcid: str | None = None
    ror: str | None = None

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str | None) -> str | None:
        """Normalize target names and treat empty strings as missing."""
        if value is None:
            return None
        name = value.strip()
        return name or None

    @field_validator("openalex_id", "orcid", "ror")
    @classmethod
    def strip_optional_identifier(cls, value: str | None) -> str | None:
        """Normalize optional identifiers and treat empty strings as missing."""
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None

    @model_validator(mode="after")
    def validate_identifier_fields(self) -> WatchTarget:
        """Validate the allowed identifier combinations for each target type."""
        if self.type == "author":
            if self.ror:
                raise ValueError("Author targets cannot define ror; use orcid or openalex_id.")
            if not (self.name or self.openalex_id or self.orcid):
                raise ValueError("Author targets need at least one of name, openalex_id, or orcid.")
        else:
            if self.orcid:
                raise ValueError("Institution targets cannot define orcid; use ror or openalex_id.")
            if not (self.name or self.openalex_id or self.ror):
                raise ValueError("Institution targets need at least one of name, openalex_id, or ror.")
        return self


class KeywordFilters(BaseModel):
    """Optional keyword filters applied after fetching papers.

    Attributes:
        include: Keywords that must appear in a paper's searchable text.
        exclude: Keywords that remove a paper from the results.

    """

    include: list[str] = Field(default_factory=list)
    exclude: list[str] = Field(default_factory=list)


class TelegramOptions(BaseModel):
    """Telegram delivery options.

    Attributes:
        send_empty_report: Whether to send a Telegram message when no new papers
            match.

    """

    send_empty_report: bool = False


class SummaryOptions(BaseModel):
    """Optional TL;DR summary generation settings.

    Attributes:
        enabled: Whether to generate per-paper summaries before formatting.
        provider: Summary provider implementation to use.

    """

    enabled: bool = False
    provider: SummaryProvider = "fake"


class TopicField(BaseModel):
    """A broad OpenAlex field filter such as Computer Science or Physics.

    Attributes:
        name: Optional human-readable field name.
        openalex_id: Optional stable OpenAlex field ID.

    """

    name: str | None = None
    openalex_id: str | None = None

    @field_validator("name", "openalex_id")
    @classmethod
    def normalize_optional_text(cls, value: str | None) -> str | None:
        """Normalize optional text fields and treat empty strings as missing."""
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None

    @model_validator(mode="after")
    def validate_identifier_fields(self) -> TopicField:
        """Require either a name or a stable OpenAlex field ID."""
        if not (self.name or self.openalex_id):
            raise ValueError("Topic fields need at least one of name or openalex_id.")
        return self


class TopicFilters(BaseModel):
    """Broad field-based filters applied to all work discovery.

    Attributes:
        match_mode: Whether to match only primary topic fields or any assigned
            topic field.
        fields: Broad OpenAlex fields to keep in the result set.

    """

    match_mode: TopicMatchMode = "primary"
    fields: list[TopicField] = Field(default_factory=list)


class GlobalQuery(BaseModel):
    """A global keyword-based discovery query.

    Attributes:
        query: Keyword query sent to OpenAlex.
        field: OpenAlex search field used for the query.
        label: Optional custom label shown in digests.

    """

    query: str
    field: GlobalQueryField = "title_and_abstract"
    label: str | None = None

    @field_validator("query")
    @classmethod
    def validate_query(cls, value: str) -> str:
        """Reject empty keyword queries."""
        query = value.strip()
        if not query:
            raise ValueError("Global query cannot be empty.")
        return query

    @field_validator("label")
    @classmethod
    def validate_label(cls, value: str | None) -> str | None:
        """Normalize optional labels and treat empty strings as missing."""
        if value is None:
            return None
        label = value.strip()
        return label or None

    def display_label(self) -> str:
        """Return the label shown in the digest."""
        return self.label or f"Query: {self.query}"


class WatchlistConfig(BaseModel):
    """Top-level watchlist configuration.

    Attributes:
        lookback_days: Number of days to search backward from the current date.
        work_types: Allowed OpenAlex work types for discovery.
        targets: Author and institution watch targets.
        topic_filters: Broad field-based topic filters.
        global_queries: Optional global keyword discovery queries.
        keywords: Post-retrieval keyword include/exclude filters.
        summaries: Optional per-paper TL;DR generation settings.
        telegram: Telegram delivery options.

    """

    lookback_days: int = 2
    work_types: list[WorkType] = Field(default_factory=lambda: ["article", "preprint"])
    targets: list[WatchTarget]
    topic_filters: TopicFilters = Field(default_factory=TopicFilters)
    global_queries: list[GlobalQuery] = Field(default_factory=list)
    keywords: KeywordFilters = Field(default_factory=KeywordFilters)
    summaries: SummaryOptions = Field(default_factory=SummaryOptions)
    telegram: TelegramOptions = Field(default_factory=TelegramOptions)

    @field_validator("work_types")
    @classmethod
    def validate_work_types(cls, value: list[WorkType]) -> list[WorkType]:
        """Normalize and deduplicate configured work types."""
        deduped = list(dict.fromkeys(value))
        if not deduped:
            raise ValueError("work_types cannot be empty.")
        return deduped

    @field_validator("lookback_days")
    @classmethod
    def validate_lookback_days(cls, value: int) -> int:
        """Ensure lookback days is non-negative."""
        if value < 0:
            raise ValueError("lookback_days must be greater than or equal to 0.")
        return value


class State(BaseModel):
    """Persisted bot state.

    Attributes:
        sent_work_ids: Raw OpenAlex work IDs that have already been sent.
        sent_paper_signatures: Collapsed paper signatures used for stronger
            duplicate suppression across runs.
        last_run_at: Timestamp of the last completed run, if any.

    """

    sent_work_ids: list[str] = Field(default_factory=list)
    sent_paper_signatures: list[str] = Field(default_factory=list)
    last_run_at: datetime | None = None


class EntityRef(BaseModel):
    """A resolved OpenAlex entity reference.

    Attributes:
        entity_type: The type of entity that was resolved.
        openalex_id: Stable OpenAlex ID for the entity.
        display_name: Human-readable OpenAlex display name.

    """

    entity_type: EntityType
    openalex_id: str
    display_name: str


class ResolvedTarget(BaseModel):
    """A watch target with a resolved stable OpenAlex ID.

    Attributes:
        type: Whether the target is an author or institution.
        name: Name used in digests and output.
        openalex_id: Stable resolved OpenAlex ID.
        resolved_name: Canonical display name returned by OpenAlex.

    """

    type: TargetType
    name: str
    openalex_id: str
    resolved_name: str


class ResolvedTopicField(BaseModel):
    """A field filter with a resolved stable OpenAlex field ID.

    Attributes:
        name: Name used in configuration and output.
        openalex_id: Stable resolved OpenAlex field ID.
        resolved_name: Canonical display name returned by OpenAlex.

    """

    name: str
    openalex_id: str
    resolved_name: str


class Paper(BaseModel):
    """Normalized paper metadata used by the bot.

    Attributes:
        work_id: Canonical OpenAlex work ID for the representative record.
        title: Paper title.
        publication_date: Publication date when available.
        doi: Normalized DOI when available.
        landing_url: Best URL to include in digests.
        abstract: Plain-text abstract when OpenAlex provides one.
        authors_summary: Compact author summary for digest output.
        lead_author: First listed author name when available.
        matched_targets: Targets or global queries that matched this paper.
        source_work_ids: Raw OpenAlex work IDs collapsed into this paper.

    """

    work_id: str
    title: str
    publication_date: date | None = None
    doi: str | None = None
    landing_url: str
    abstract: str | None = None
    authors_summary: str
    lead_author: str | None = None
    matched_targets: list[str] = Field(default_factory=list)
    source_work_ids: list[str] = Field(default_factory=list)

    def searchable_text(self) -> str:
        """Return normalized text used for keyword filtering.

        Returns:
            A lower-cased string containing the paper title, author summary, and
            matched targets.

        """
        return " ".join([self.title, self.authors_summary, " ".join(self.matched_targets)]).casefold()


class RuntimeConfig(BaseModel):
    """Resolved runtime settings for a command invocation.

    Attributes:
        project_root: Repository root for the current command.
        watchlist_path: Path to the private watchlist YAML file.
        state_path: Path to the persisted JSON state file.
        watchlist: Validated watchlist configuration.
        openalex_api_key: OpenAlex API key from the environment.
        telegram_bot_token: Telegram bot token from the environment.
        telegram_chat_id: Telegram chat ID from the environment.

    """

    project_root: Path
    watchlist_path: Path
    state_path: Path
    watchlist: WatchlistConfig
    openalex_api_key: str | None = None
    telegram_bot_token: str | None = None
    telegram_chat_id: str | None = None


class RunResult(BaseModel):
    """Summary of a completed run.

    Attributes:
        resolved_target_count: Number of resolved author/institution targets.
        fetched_paper_count: Number of papers remaining after keyword filters.
        new_paper_count: Number of unsent papers included in the digest.
        message_sent: Whether at least one Telegram message was sent.
        state_path: Path to the updated persisted state file.

    """

    resolved_target_count: int
    fetched_paper_count: int
    new_paper_count: int
    message_sent: bool
    state_path: Path
