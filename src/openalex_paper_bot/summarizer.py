"""Generate optional per-paper summaries for digest rendering."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from openalex_paper_bot.models import Paper, SummaryOptions, SummaryProvider

DEFAULT_SUMMARY_LIMIT = 220


class PaperSummarizer(Protocol):
    """Interface implemented by summary providers."""

    def summarize(self, papers: Sequence[Paper]) -> dict[str, str]:
        """Return summaries keyed by paper work ID."""


class FakePaperSummarizer:
    """Deterministic summary provider used to exercise the summary pipeline."""

    def summarize(self, papers: Sequence[Paper]) -> dict[str, str]:
        """Return first-sentence abstract snippets keyed by paper work ID."""
        summaries: dict[str, str] = {}
        for paper in papers:
            if not paper.abstract:
                continue
            summary = _first_sentence(paper.abstract)
            if summary:
                summaries[paper.work_id] = _truncate(summary, DEFAULT_SUMMARY_LIMIT)
        return summaries


def build_summarizer(provider: SummaryProvider) -> PaperSummarizer:
    """Create a summarizer for a configured provider."""
    if provider == "fake":
        return FakePaperSummarizer()
    raise ValueError(f"Unsupported summary provider: {provider}")


def build_paper_summaries(papers: Sequence[Paper], options: SummaryOptions) -> dict[str, str]:
    """Generate summaries for papers when summary generation is enabled."""
    if not options.enabled:
        return {}

    eligible_papers = [paper for paper in papers if paper.abstract]
    if not eligible_papers:
        return {}

    return build_summarizer(options.provider).summarize(eligible_papers)


def _first_sentence(text: str) -> str:
    normalized = " ".join(text.split())
    for index, character in enumerate(normalized):
        if character in {".", "?", "!"} and (index == len(normalized) - 1 or normalized[index + 1].isspace()):
            return normalized[: index + 1]
    return normalized


def _truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 3].rstrip() + "..."
