"""Generate optional per-paper summaries for digest rendering.

The summarizer layer keeps provider-specific summary generation separate from
digest formatting. It supports a deterministic fake provider for tests and an
Ollama-backed provider for local and GitHub Actions runs.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Sequence
from typing import Any, Protocol, cast

import httpx

from openalex_paper_bot.models import Paper, SummaryOptions, SummaryProvider

DEFAULT_OLLAMA_BASE_URL = "https://ollama.com/v1"
SUMMARY_SYSTEM_PROMPT = (
    "You write terse, neutral summaries of academic papers for a Telegram digest. "
    "Use only the provided abstract. Return one compact sentence. "
    "Do not start with 'This paper' or 'The paper'. Do not mention missing information, "
    "do not use markdown, and do not add hype."
)
SUMMARY_PROMPT_BUFFER_CHARS = 20

logger = logging.getLogger(__name__)


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


class OllamaSummarizer:
    """Ollama-backed paper summarizer."""

    def __init__(
        self,
        *,
        base_url: str = DEFAULT_OLLAMA_BASE_URL,
        api_key: str | None = None,
        model: str,
        max_chars: int,
        timeout: float = 20.0,
        client: httpx.Client | None = None,
    ) -> None:
        """Initialize the Ollama summarizer.

        Args:
            base_url: Ollama API base URL.
            api_key: Optional API key for Ollama Cloud authentication.
            model: Ollama model identifier.
            max_chars: Maximum number of summary characters to return.
            timeout: Request timeout in seconds.
            client: Optional HTTP client, primarily used by tests.

        """
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
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
        """Generate a single summary with the Ollama chat API.

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
        url = f"{self.base_url}/chat/completions"
        headers: dict[str, str] = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        try:
            response = self._client.post(
                url,
                headers=headers,
                json=payload,
            )
            response.raise_for_status()
            raw_response_data = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            logger.warning("Summary request failed for %s: %s", paper.work_id, exc)
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
    ollama_api_key: str | None = None,
    ollama_base_url: str = DEFAULT_OLLAMA_BASE_URL,
) -> PaperSummarizer | None:
    """Create a summarizer for a configured provider.

    Args:
        provider: Summary provider name from the watchlist config.
        model: Ollama model identifier.
        max_chars: Maximum number of summary characters to render.
        ollama_api_key: Optional API key for Ollama Cloud authentication.
        ollama_base_url: Ollama API base URL.

    Returns:
        A configured summarizer, or ``None`` when provider credentials are missing.

    Raises:
        ValueError: If ``provider`` is unsupported.

    """
    if provider == "fake":
        return FakePaperSummarizer(max_chars=max_chars)
    if provider == "ollama":
        return OllamaSummarizer(
            base_url=ollama_base_url,
            api_key=ollama_api_key,
            model=model,
            max_chars=max_chars,
        )
    raise ValueError(f"Unsupported summary provider: {provider}")


def build_paper_summaries(
    papers: Sequence[Paper],
    options: SummaryOptions,
    *,
    ollama_api_key: str | None = None,
    ollama_base_url: str = DEFAULT_OLLAMA_BASE_URL,
) -> dict[str, str]:
    """Generate summaries for papers when summary generation is enabled.

    Args:
        papers: Candidate papers for the outgoing digest.
        options: Summary generation settings from the watchlist.
        ollama_api_key: Optional API key for Ollama Cloud authentication.
        ollama_base_url: Ollama API base URL.

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
        ollama_api_key=ollama_api_key,
        ollama_base_url=ollama_base_url,
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
    return (
        "Write one compact sentence focused on the paper's key contribution. "
        "Use at most 14 words. "
        "Do not start with 'This paper' or 'The paper'.\n\n"
        f"Abstract:\n{paper.abstract}"
    )


def _strip_think_blocks(text: str) -> str:
    """Remove ``<think>...</think>`` blocks that some models emit.

    Args:
        text: Raw model response text.

    Returns:
        The text with any think blocks removed.

    """
    return re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()


def _extract_chat_completion_content(response_data: dict[str, Any]) -> str | None:
    """Extract assistant text from a chat completions response.

    Args:
        response_data: Decoded chat completions response.

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
    normalized = _strip_think_blocks(summary)
    normalized = " ".join(normalized.strip('"').split())
    if not normalized:
        return None
    prefixes = ("TL;DR:", "Summary:")
    for prefix in prefixes:
        if normalized.casefold().startswith(prefix.casefold()):
            normalized = normalized[len(prefix) :].strip()
            break
    return _truncate(normalized, max_chars)
