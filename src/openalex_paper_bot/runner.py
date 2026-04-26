"""Coordinate the end-to-end workflow for fetching and sending paper alerts.

The runner ties together configuration loading, target resolution, OpenAlex
fetching, duplicate suppression, digest formatting, Telegram delivery, and
state persistence.
"""

from __future__ import annotations

import re
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Protocol, cast

import yaml

from openalex_paper_bot.config import load_runtime_config
from openalex_paper_bot.formatter import build_digest_messages
from openalex_paper_bot.models import (
    EntityRef,
    GlobalQueryField,
    Paper,
    ResolvedTarget,
    ResolvedTopicField,
    RunResult,
    RuntimeConfig,
    TopicMatchMode,
    WatchlistConfig,
    WorkType,
)
from openalex_paper_bot.openalex import OpenAlexClient
from openalex_paper_bot.storage import read_state, updated_state, write_state
from openalex_paper_bot.summarizer import build_paper_summaries
from openalex_paper_bot.telegram import TelegramClient


class _TargetResolutionClient(Protocol):
    """OpenAlex-like client methods needed for target and field resolution."""

    def get_author(self, author_id: str) -> EntityRef: ...
    def get_institution(self, inst_id: str) -> EntityRef: ...
    def resolve_author_by_orcid(self, orcid: str) -> EntityRef: ...
    def resolve_institution_by_ror(self, ror: str) -> EntityRef: ...
    def resolve_author(self, name: str) -> EntityRef: ...
    def resolve_institution(self, name: str) -> EntityRef: ...
    def get_field(self, field_id: str) -> EntityRef: ...
    def resolve_field(self, name: str) -> EntityRef: ...


class _PaperDiscoveryClient(Protocol):
    """OpenAlex-like client methods needed for paper discovery."""

    def topic_field_filters(self, field_ids: list[str], *, match_mode: TopicMatchMode) -> list[str]: ...

    def fetch_recent_works_for_author(
        self,
        author_id: str,
        from_date: date,
        *,
        work_types: list[WorkType],
        topic_filters: list[str] | None = None,
    ) -> list[Paper]: ...

    def fetch_recent_works_for_institution(
        self,
        inst_id: str,
        from_date: date,
        *,
        work_types: list[WorkType],
        topic_filters: list[str] | None = None,
    ) -> list[Paper]: ...

    def fetch_recent_works_for_query(
        self,
        query: str,
        from_date: date,
        *,
        field: GlobalQueryField = "title_and_abstract",
        work_types: list[WorkType],
        topic_filters: list[str] | None = None,
    ) -> list[Paper]: ...


def run(project_root: Path | None = None, *, today: date | None = None) -> RunResult:
    """Run the daily paper alert flow.

    Args:
        project_root: Optional explicit project root.
        today: Optional current date override for testing.

    Returns:
        A summary of the completed run.

    """
    config = load_runtime_config(
        project_root=project_root,
        require_openalex=True,
        require_telegram=True,
    )
    current_date = today or datetime.now().date()
    executed_at = datetime.now(UTC)
    from_date = current_date - timedelta(days=config.watchlist.lookback_days)
    state = read_state(config.state_path)

    with OpenAlexClient(config.openalex_api_key or "") as openalex_client:
        resolved_targets = resolve_targets(config.watchlist, openalex_client)
        resolved_topic_fields = resolve_topic_fields(config.watchlist, openalex_client)
        papers = fetch_papers(
            config,
            resolved_targets,
            resolved_topic_fields,
            openalex_client,
            from_date=from_date,
        )

    filtered_papers = filter_papers_by_keywords(
        papers,
        include=config.watchlist.keywords.include,
        exclude=config.watchlist.keywords.exclude,
    )
    new_papers = drop_previously_sent(
        filtered_papers,
        sent_work_ids=state.sent_work_ids,
        sent_paper_signatures=state.sent_paper_signatures,
    )
    target_order = [
        *[target.name for target in resolved_targets],
        *[query.display_label() for query in config.watchlist.global_queries],
    ]

    message_sent = False
    if new_papers:
        summaries = build_paper_summaries(new_papers, config.watchlist.summaries)
        digests = build_digest_messages(new_papers, target_order=target_order, summaries=summaries)
        with TelegramClient(
            config.telegram_bot_token or "",
            config.telegram_chat_id or "",
        ) as telegram_client:
            for digest in digests:
                telegram_client.send_message(digest, parse_mode="HTML")
        message_sent = True
        state = updated_state(
            state,
            new_work_ids=[work_id for paper in new_papers for work_id in (paper.source_work_ids or [paper.work_id])],
            new_paper_signatures=[
                signature for paper in new_papers for signature in _paper_equivalence_signatures(paper)
            ],
            executed_at=executed_at,
        )
    else:
        if config.watchlist.telegram.send_empty_report:
            with TelegramClient(
                config.telegram_bot_token or "",
                config.telegram_chat_id or "",
            ) as telegram_client:
                telegram_client.send_message("No new matching papers.")
            message_sent = True
        state = updated_state(state, new_work_ids=[], new_paper_signatures=[], executed_at=executed_at)

    write_state(config.state_path, state)
    return RunResult(
        resolved_target_count=len(resolved_targets),
        fetched_paper_count=len(filtered_papers),
        new_paper_count=len(new_papers),
        message_sent=message_sent,
        state_path=config.state_path,
    )


def resolve_targets(watchlist: WatchlistConfig, client: _TargetResolutionClient) -> list[ResolvedTarget]:
    """Resolve all watchlist targets to stable OpenAlex IDs.

    Args:
        watchlist: Watchlist configuration to resolve.
        client: OpenAlex client used for entity lookup.

    Returns:
        Resolved targets in watchlist order.

    """
    resolved: list[ResolvedTarget] = []
    for target in watchlist.targets:
        if target.openalex_id:
            entity = (
                client.get_author(target.openalex_id)
                if target.type == "author"
                else client.get_institution(target.openalex_id)
            )
            resolved.append(
                ResolvedTarget(
                    type=target.type,
                    name=target.name or entity.display_name,
                    openalex_id=entity.openalex_id,
                    resolved_name=entity.display_name,
                )
            )
            continue

        if target.type == "author" and target.orcid:
            entity = client.resolve_author_by_orcid(target.orcid)
        elif target.type == "institution" and target.ror:
            entity = client.resolve_institution_by_ror(target.ror)
        elif target.type == "author":
            entity = client.resolve_author(target.name or "")
        else:
            entity = client.resolve_institution(target.name or "")
        resolved.append(
            ResolvedTarget(
                type=target.type,
                name=target.name or entity.display_name,
                openalex_id=entity.openalex_id,
                resolved_name=entity.display_name,
            )
        )
    return resolved


def resolve_topic_fields(
    watchlist: WatchlistConfig,
    client: _TargetResolutionClient,
) -> list[ResolvedTopicField]:
    """Resolve all configured broad topic fields to stable OpenAlex field IDs.

    Args:
        watchlist: Watchlist configuration to resolve.
        client: OpenAlex client used for field lookup.

    Returns:
        Resolved topic fields in watchlist order.

    """
    resolved: list[ResolvedTopicField] = []
    for field in watchlist.topic_filters.fields:
        if field.openalex_id:
            entity = client.get_field(field.openalex_id)
            resolved.append(
                ResolvedTopicField(
                    name=field.name or entity.display_name,
                    openalex_id=entity.openalex_id,
                    resolved_name=entity.display_name,
                )
            )
            continue

        entity = client.resolve_field(field.name or "")
        resolved.append(
            ResolvedTopicField(
                name=field.name or entity.display_name,
                openalex_id=entity.openalex_id,
                resolved_name=entity.display_name,
            )
        )
    return resolved


def fetch_papers(
    config: RuntimeConfig,
    resolved_targets: list[ResolvedTarget],
    resolved_topic_fields: list[ResolvedTopicField],
    client: _PaperDiscoveryClient,
    *,
    from_date: date,
) -> list[Paper]:
    """Fetch and deduplicate recent papers across all configured discovery sources.

    Args:
        config: Runtime configuration for the current command.
        resolved_targets: Resolved author and institution targets.
        resolved_topic_fields: Resolved field-based topic filters.
        client: OpenAlex client used for work discovery.
        from_date: Inclusive publication date lower bound.

    Returns:
        The merged, deduplicated, and sorted list of discovered papers.

    """
    deduped: dict[str, Paper] = {}
    topic_filters = client.topic_field_filters(
        [field.openalex_id for field in resolved_topic_fields],
        match_mode=config.watchlist.topic_filters.match_mode,
    )

    for target in resolved_targets:
        papers = (
            client.fetch_recent_works_for_author(
                target.openalex_id,
                from_date,
                work_types=config.watchlist.work_types,
                topic_filters=topic_filters,
            )
            if target.type == "author"
            else client.fetch_recent_works_for_institution(
                target.openalex_id,
                from_date,
                work_types=config.watchlist.work_types,
                topic_filters=topic_filters,
            )
        )
        _merge_papers(deduped, papers, label=target.name)

    for query in config.watchlist.global_queries:
        papers = client.fetch_recent_works_for_query(
            query.query,
            from_date,
            field=query.field,
            work_types=config.watchlist.work_types,
            topic_filters=topic_filters,
        )
        _merge_papers(deduped, papers, label=query.display_label())

    papers = collapse_equivalent_papers(list(deduped.values()))
    papers.sort(key=lambda paper: paper.title.casefold())
    papers.sort(key=lambda paper: paper.publication_date or date.min, reverse=True)
    return papers


def _merge_papers(deduped: dict[str, Paper], papers: list[Paper], *, label: str) -> None:
    """Merge a source's papers into the deduped result map.

    Args:
        deduped: Mapping of canonical work IDs to accumulated papers.
        papers: Papers returned by a discovery source.
        label: Matched target or query label to attach to each paper.

    """
    for paper in papers:
        existing = deduped.get(paper.work_id)
        if existing is None:
            deduped[paper.work_id] = paper.model_copy(update={"matched_targets": [label]})
            continue
        if label not in existing.matched_targets:
            existing.matched_targets.append(label)


def collapse_equivalent_papers(papers: list[Paper]) -> list[Paper]:
    """Collapse obvious duplicate versions of the same paper.

    Args:
        papers: Candidate papers to collapse.

    Returns:
        A list with equivalent papers merged into a single representative item.

    """
    collapsed: list[Paper] = []
    signature_to_index: dict[str, int] = {}
    for paper in papers:
        matching_indexes = {
            signature_to_index[signature]
            for signature in _paper_equivalence_signatures(paper)
            if signature in signature_to_index
        }
        if not matching_indexes:
            collapsed.append(paper)
            group_index = len(collapsed) - 1
        else:
            group_index = min(matching_indexes)
            merged = collapsed[group_index]
            for other_index in sorted(matching_indexes - {group_index}, reverse=True):
                merged = _merge_equivalent_paper_pair(merged, collapsed[other_index])
                collapsed.pop(other_index)
                signature_to_index = {
                    key: (index - 1 if index > other_index else index) for key, index in signature_to_index.items()
                }
            collapsed[group_index] = _merge_equivalent_paper_pair(merged, paper)

        for signature in _paper_equivalence_signatures(collapsed[group_index]):
            signature_to_index[signature] = group_index
    return collapsed


def _paper_equivalence_signatures(paper: Paper) -> list[str]:
    """Return signatures used to collapse duplicate work versions."""
    signatures: list[str] = []
    if paper.doi:
        signatures.append(f"doi:{paper.doi}")

    normalized_title = _normalize_text(paper.title)
    normalized_lead_author = _normalize_text(paper.lead_author or "")
    if normalized_title:
        signatures.append(f"title:{normalized_title}|lead:{normalized_lead_author}")
    return signatures


def _merge_equivalent_paper_pair(left: Paper, right: Paper) -> Paper:
    """Merge two equivalent papers into a single representative record.

    Args:
        left: First paper candidate.
        right: Second paper candidate.

    Returns:
        The preferred paper record with merged targets and source IDs.

    """
    preferred, other = sorted(
        [left, right],
        key=_paper_preference_key,
        reverse=True,
    )
    matched_targets = list(dict.fromkeys([*preferred.matched_targets, *other.matched_targets]))
    source_work_ids = list(
        dict.fromkeys(
            [
                *(preferred.source_work_ids or [preferred.work_id]),
                *(other.source_work_ids or [other.work_id]),
            ]
        )
    )
    return cast(
        Paper,
        preferred.model_copy(
            update={
                "matched_targets": matched_targets,
                "source_work_ids": source_work_ids,
                "doi": preferred.doi or other.doi,
                "abstract": preferred.abstract or other.abstract,
                "lead_author": preferred.lead_author or other.lead_author,
                "authors_summary": preferred.authors_summary
                if preferred.authors_summary != "Unknown authors"
                else other.authors_summary,
            }
        ),
    )


def _paper_preference_key(paper: Paper) -> tuple[int, int, date, int]:
    """Return ordering used to choose the representative paper record."""
    return (
        1 if paper.doi else 0,
        _landing_url_priority(paper.landing_url),
        paper.publication_date or date.min,
        len(paper.matched_targets),
    )


def _landing_url_priority(url: str) -> int:
    """Rank landing URLs so publisher or DOI links win over weaker alternatives."""
    normalized = url.casefold()
    if "doi.org/" in normalized:
        return 3
    if "arxiv.org/" in normalized:
        return 1
    if normalized.startswith("https://openalex.org/"):
        return 0
    return 2


def _normalize_text(value: str) -> str:
    """Normalize free text for fuzzy signature matching."""
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", value.casefold())).strip()


def filter_papers_by_keywords(
    papers: list[Paper],
    *,
    include: list[str],
    exclude: list[str],
) -> list[Paper]:
    """Apply optional include/exclude keyword filters after retrieval.

    Args:
        papers: Candidate papers to filter.
        include: Lower-priority inclusion keywords.
        exclude: Exclusion keywords that should remove a paper.

    Returns:
        The subset of papers that match the keyword filters.

    """
    include_terms = [term.casefold() for term in include if term.strip()]
    exclude_terms = [term.casefold() for term in exclude if term.strip()]

    filtered: list[Paper] = []
    for paper in papers:
        searchable = paper.searchable_text()
        if include_terms and not any(term in searchable for term in include_terms):
            continue
        if exclude_terms and any(term in searchable for term in exclude_terms):
            continue
        filtered.append(paper)
    return filtered


def drop_previously_sent(
    papers: list[Paper],
    *,
    sent_work_ids: list[str],
    sent_paper_signatures: list[str] | None = None,
) -> list[Paper]:
    """Remove papers already present in the persisted state.

    Args:
        papers: Candidate papers for the current run.
        sent_work_ids: Raw work IDs that were sent in prior runs.
        sent_paper_signatures: Collapsed paper signatures sent in prior runs.

    Returns:
        Papers that have not already been sent.

    """
    already_sent = set(sent_work_ids)
    already_sent_signatures = set(sent_paper_signatures or [])
    filtered: list[Paper] = []
    for paper in papers:
        source_ids = set(paper.source_work_ids or [paper.work_id])
        if source_ids & already_sent:
            continue
        paper_signatures = set(_paper_equivalence_signatures(paper))
        if paper_signatures & already_sent_signatures:
            continue
        filtered.append(paper)
    return filtered


def resolve_watchlist(
    project_root: Path | None = None,
    *,
    write: bool = False,
) -> tuple[RuntimeConfig, list[ResolvedTarget], list[ResolvedTopicField]]:
    """Resolve watchlist entities and optionally write stable IDs back to YAML.

    Args:
        project_root: Optional explicit project root.
        write: Whether to persist resolved IDs into ``watchlist.yaml``.

    Returns:
        The runtime configuration plus resolved targets and topic fields.

    """
    config = load_runtime_config(
        project_root=project_root,
        require_openalex=True,
        require_telegram=False,
    )
    with OpenAlexClient(config.openalex_api_key or "") as openalex_client:
        resolved_targets = resolve_targets(config.watchlist, openalex_client)
        resolved_topic_fields = resolve_topic_fields(config.watchlist, openalex_client)

    if write:
        raw_watchlist = yaml.safe_load(config.watchlist_path.read_text(encoding="utf-8")) or {}
        targets = raw_watchlist.get("targets") or []
        for target, resolved_target in zip(targets, resolved_targets, strict=True):
            target["openalex_id"] = resolved_target.openalex_id
            if not target.get("name"):
                target["name"] = resolved_target.resolved_name
        topic_filters = raw_watchlist.setdefault("topic_filters", {})
        topic_filter_fields = topic_filters.get("fields") or []
        for field, resolved_field in zip(topic_filter_fields, resolved_topic_fields, strict=True):
            field["openalex_id"] = resolved_field.openalex_id
            if not field.get("name"):
                field["name"] = resolved_field.resolved_name
        config.watchlist_path.write_text(
            render_watchlist_yaml(raw_watchlist),
            encoding="utf-8",
        )

    return config, resolved_targets, resolved_topic_fields


def render_watchlist_yaml(raw_watchlist: dict[object, object]) -> str:
    """Render watchlist YAML with readable top-level spacing and indented lists.

    Args:
        raw_watchlist: Raw watchlist mapping to serialize.

    Returns:
        A human-readable YAML string ending with a trailing newline.

    """
    rendered = yaml.dump(
        raw_watchlist,
        Dumper=_WatchlistDumper,
        sort_keys=False,
        allow_unicode=False,
        default_flow_style=False,
    ).rstrip()
    lines = rendered.splitlines()
    formatted: list[str] = []
    for index, line in enumerate(lines):
        if index and line and not line.startswith((" ", "-")):
            formatted.append("")
        formatted.append(line)
    return "\n".join(formatted) + "\n"


class _WatchlistDumper(yaml.SafeDumper):
    """YAML dumper that indents list items under their parent keys."""

    def increase_indent(self, flow: bool = False, indentless: bool = False) -> None:
        """Force nested sequence indentation for readable YAML output."""
        return super().increase_indent(flow, indentless=False)


def send_test_message(project_root: Path | None = None, *, text: str | None = None) -> None:
    """Send a small Telegram test message.

    Args:
        project_root: Optional explicit project root.
        text: Optional custom message body.

    """
    config = load_runtime_config(
        project_root=project_root,
        require_openalex=False,
        require_telegram=True,
    )
    message = text or (f"openalex-paper-bot test message\nUTC time: {datetime.now(UTC).isoformat(timespec='seconds')}")
    with TelegramClient(
        config.telegram_bot_token or "",
        config.telegram_chat_id or "",
    ) as telegram_client:
        telegram_client.send_message(message)
