"""Generate optional per-paper summaries for digest rendering.

The summarizer layer keeps provider-specific summary generation separate from
digest formatting. It supports a deterministic fake provider for tests and a
GitHub Models-backed provider for local and GitHub Actions runs.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Protocol, cast

import httpx

from openalex_paper_bot.models import Paper, SummaryOptions, SummaryProvider

GITHUB_MODELS_CHAT_COMPLETIONS_URL = "https://models.github.ai/inference/chat/completions"
GITHUB_API_VERSION = "2026-03-10"
SUMMARY_SYSTEM_PROMPT = (
    "You write terse, neutral summaries of academic papers for a Telegram digest. "
    "Use only the provided abstract. Return one compact sentence. "
    "Do not start with 'This paper' or 'The paper'. Do not mention missing information, "
    "do not use markdown, and do not add hype."
)
SUMMARY_PROMPT_BUFFER_CHARS = 20


class PaperSummarizer(Protocol):
    """Interface implemented by summary providers."""

    def summarize(self, papers: Sequence[Paper]) -> dict[str, str]:
        """Return summaries keyed by paper work ID.

        Args:
            papers: Papers to summarize.

        Returns:
            Summary text keyed by canonical OpenAlex work ID.

        """


class FakePaperSummarizer:
    """Deterministic summary provider used to exercise the summary pipeline."""

    def __init__(self, *, max_chars: int) -> None:
        """Initialize the fake provider.

        Args:
            max_chars: Maximum number of summary characters to return.

        """
        self.max_chars = max_chars

    def summarize(self, papers: Sequence[Paper]) -> dict[str, str]:
        """Return first-sentence abstract snippets keyed by paper work ID.

        Args:
            papers: Papers to summarize.

        Returns:
            First-sentence summaries keyed by canonical OpenAlex work ID.

        """
        summaries: dict[str, str] = {}
        for paper in papers:
            if not paper.abstract:
                continue
            summary = _first_sentence(paper.abstract)
            if summary:
                summaries[paper.work_id] = _truncate(summary, self.max_chars)
        return summaries


class GitHubModelsSummarizer:
    """GitHub Models-backed paper summarizer."""

    def __init__(
        self,
        *,
        token: str,
        model: str,
        max_chars: int,
        timeout: float = 20.0,
        client: httpx.Client | None = None,
    ) -> None:
        """Initialize the GitHub Models summarizer.

        Args:
            token: GitHub token with Models access.
            model: GitHub Models model identifier.
            max_chars: Maximum number of summary characters to return.
            timeout: Request timeout in seconds.
            client: Optional HTTP client, primarily used by tests.

        """
        self.token = token
        self.model = model
        self.max_chars = max_chars
        self._owns_client = client is None
        self._client = client or httpx.Client(timeout=timeout)

    def summarize(self, papers: Sequence[Paper]) -> dict[str, str]:
        """Return model-generated summaries keyed by paper work ID.

        Args:
            papers: Papers to summarize.

        Returns:
            Model-generated summaries keyed by canonical OpenAlex work ID.

        """
        summaries: dict[str, str] = {}
        for paper in papers:
            if not paper.abstract:
                continue
            summary = self._summarize_paper(paper)
            if summary:
                summaries[paper.work_id] = summary
        return summaries

    def close(self) -> None:
        """Close the underlying HTTP client if this instance owns it."""
        if self._owns_client:
            self._client.close()

    def _summarize_paper(self, paper: Paper) -> str | None:
        """Generate a single summary with the GitHub Models chat API.

        Args:
            paper: Paper to summarize.

        Returns:
            Cleaned summary text, or ``None`` when the provider call fails.

        """
        prompt_limit = _summary_prompt_limit(self.max_chars)
        payload = {
            "model": self.model,
            "temperature": 0,
            "max_tokens": _summary_token_limit(prompt_limit),
            "messages": [
                {"role": "system", "content": SUMMARY_SYSTEM_PROMPT},
                {"role": "user", "content": _summary_user_prompt(paper, prompt_limit)},
            ],
        }
        try:
            response = self._client.post(
                GITHUB_MODELS_CHAT_COMPLETIONS_URL,
                headers={
                    "Accept": "application/vnd.github+json",
                    "Authorization": f"Bearer {self.token}",
                    "Content-Type": "application/json",
                    "X-GitHub-Api-Version": GITHUB_API_VERSION,
                },
                json=payload,
            )
            response.raise_for_status()
            raw_response_data = response.json()
        except (httpx.HTTPError, ValueError):
            return None

        if not isinstance(raw_response_data, dict):
            return None
        response_data = cast(dict[str, Any], raw_response_data)
        return _clean_summary(_extract_chat_completion_content(response_data), self.max_chars)


def build_summarizer(
    provider: SummaryProvider,
    *,
    model: str,
    max_chars: int,
    github_models_token: str | None = None,
) -> PaperSummarizer | None:
    """Create a summarizer for a configured provider.

    Args:
        provider: Summary provider name from the watchlist config.
        model: GitHub Models model identifier.
        max_chars: Maximum number of summary characters to render.
        github_models_token: Optional GitHub token for the GitHub Models provider.

    Returns:
        A configured summarizer, or ``None`` when provider credentials are missing.

    Raises:
        ValueError: If ``provider`` is unsupported.

    """
    if provider == "fake":
        return FakePaperSummarizer(max_chars=max_chars)
    if provider == "github_models":
        if not github_models_token:
            return None
        return GitHubModelsSummarizer(token=github_models_token, model=model, max_chars=max_chars)
    raise ValueError(f"Unsupported summary provider: {provider}")


def build_paper_summaries(
    papers: Sequence[Paper],
    options: SummaryOptions,
    *,
    github_models_token: str | None = None,
) -> dict[str, str]:
    """Generate summaries for papers when summary generation is enabled.

    Args:
        papers: Candidate papers for the outgoing digest.
        options: Summary generation settings from the watchlist.
        github_models_token: Optional GitHub token for the GitHub Models provider.

    Returns:
        Summary text keyed by canonical OpenAlex work ID.

    """
    if not options.enabled:
        return {}

    eligible_papers = [paper for paper in papers if paper.abstract]
    if not eligible_papers:
        return {}

    summarizer = build_summarizer(
        options.provider,
        model=options.model,
        max_chars=options.max_chars,
        github_models_token=github_models_token,
    )
    if summarizer is None:
        return {}

    try:
        return summarizer.summarize(eligible_papers)
    finally:
        close = getattr(summarizer, "close", None)
        if callable(close):
            close()


def _first_sentence(text: str) -> str:
    """Extract the first sentence from text.

    Args:
        text: Source text to inspect.

    Returns:
        The first sentence when punctuation is found, otherwise normalized text.

    """
    normalized = " ".join(text.split())
    for index, character in enumerate(normalized):
        if character in {".", "?", "!"} and (index == len(normalized) - 1 or normalized[index + 1].isspace()):
            return normalized[: index + 1]
    return normalized


def _truncate(text: str, limit: int) -> str:
    """Truncate text to a display limit, preferring word boundaries.

    Args:
        text: Text to truncate.
        limit: Maximum number of characters to return.

    Returns:
        The original text or an ellipsis-suffixed truncated version.

    """
    if len(text) <= limit:
        return text
    cutoff = limit - 3
    truncated = text[:cutoff].rstrip()
    if cutoff < len(text) and text[cutoff].strip():
        boundary = truncated.rfind(" ")
        if boundary >= limit // 2:
            truncated = truncated[:boundary].rstrip(" ,;:-")
    return truncated + "..."


def _summary_prompt_limit(max_chars: int) -> int:
    """Return the stricter length used inside the model prompt.

    Args:
        max_chars: Configured rendering limit.

    Returns:
        The prompt-facing limit after applying a small safety buffer.

    """
    if max_chars <= SUMMARY_PROMPT_BUFFER_CHARS * 3:
        return max_chars
    return max(40, max_chars - SUMMARY_PROMPT_BUFFER_CHARS)


def _summary_token_limit(max_chars: int) -> int:
    """Estimate a token budget from a character budget.

    Args:
        max_chars: Prompt-facing character budget.

    Returns:
        A conservative max-token value for the chat completion request.

    """
    return max(32, min(160, max_chars // 3 + 24))


def _summary_user_prompt(paper: Paper, max_chars: int) -> str:
    """Build the user message sent to the summary model.

    Args:
        paper: Paper metadata and abstract to summarize.
        max_chars: Prompt-facing character budget.

    Returns:
        The user prompt for a single paper.

    """
    # Previous prompt kept temporarily while we compare summary quality:
    # f"Write a TL;DR of at most {max_chars} characters for this paper. "
    # "Aim for 8-12 words and do not use the full limit if fewer words are enough.\n\n"
    # "Write a 1-sentence summary focused on the key contribution. "
    # f"Keep it under {max_chars} characters. Use only the title and abstract. "
    # "Do not start with 'This paper' or 'The paper'.\n\n"
    # "Write a compact 8-10 word summary focused on the key contribution. "
    # "Prefer a phrase over a full sentence. "
    # f"Keep it under {max_chars} characters. Use only the title and abstract. "
    # "Do not start with 'This paper' or 'The paper'.\n\n"
    return (
        "Write one compact sentence focused on the paper's key contribution. "
        "Use at most 14 words. "
        "Do not start with 'This paper' or 'The paper'.\n\n"
        f"Abstract:\n{paper.abstract}"
    )


def _extract_chat_completion_content(response_data: dict[str, Any]) -> str | None:
    """Extract assistant text from a chat completions response.

    Args:
        response_data: Decoded GitHub Models chat completions response.

    Returns:
        The first assistant message content, or ``None`` when unavailable.

    """
    choices = response_data.get("choices")
    if not isinstance(choices, list) or not choices:
        return None
    first_choice = choices[0]
    if not isinstance(first_choice, dict):
        return None
    message = first_choice.get("message")
    if not isinstance(message, dict):
        return None
    content = message.get("content")
    return content if isinstance(content, str) else None


def _clean_summary(summary: str | None, max_chars: int) -> str | None:
    """Normalize and truncate provider-returned summary text.

    Args:
        summary: Raw provider text.
        max_chars: Maximum number of summary characters to return.

    Returns:
        Cleaned summary text, or ``None`` when the provider returned no content.

    """
    if not summary:
        return None
    normalized = " ".join(summary.strip().strip('"').split())
    if not normalized:
        return None
    prefixes = ("TL;DR:", "Summary:")
    for prefix in prefixes:
        if normalized.casefold().startswith(prefix.casefold()):
            normalized = normalized[len(prefix) :].strip()
            break
    return _truncate(normalized, max_chars)
