"""Format normalized papers into compact Telegram digest messages.

The formatter renders papers as a flat chronological list, enforces Telegram
message length limits, and emits explicit omission notes when the full digest
does not fit.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from html import escape

from openalex_paper_bot.models import Paper

MAX_MESSAGE_LENGTH = 4096
DEFAULT_MAX_MESSAGES = 3
LAST_MESSAGE_FOOTER_RESERVE = 160


def build_digest(
    papers: Sequence[Paper],
    *,
    summaries: Mapping[str, str] | None = None,
    max_length: int = MAX_MESSAGE_LENGTH,
) -> str:
    """Build a single digest message.

    Args:
        papers: Papers to include in the digest.
        summaries: Optional summaries keyed by paper work ID.
        max_length: Maximum Telegram message length to target.

    Returns:
        A single formatted digest message. If the input is too large, the
        result includes an omission note.

    """
    return build_digest_messages(
        papers,
        summaries=summaries,
        max_length=max_length,
        max_messages=1,
    )[0]


def build_digest_messages(
    papers: Sequence[Paper],
    *,
    summaries: Mapping[str, str] | None = None,
    max_length: int = MAX_MESSAGE_LENGTH,
    max_messages: int = DEFAULT_MAX_MESSAGES,
) -> list[str]:
    """Build one or more compact digest messages.

    Papers are rendered as a flat list in the order received. Each paper
    includes a match line showing why it appeared in the digest.

    Args:
        papers: Papers to include in the digest.
        summaries: Optional summaries keyed by paper work ID.
        max_length: Maximum length for each Telegram message.
        max_messages: Maximum number of Telegram messages to produce.

    Returns:
        A list of digest messages. The last message includes an omission note
        when not all papers fit.

    """
    if not papers:
        return ["No new matching papers."]

    summary_lookup = summaries or {}
    messages: list[str] = []
    index = 0
    total_count = len(papers)

    while index < total_count and len(messages) < max_messages:
        is_last_message = len(messages) == max_messages - 1
        header = [_message_header(total_count, continued=bool(messages))]
        blocks: list[list[str]] = []

        while index < total_count:
            paper = papers[index]
            block = ["", *_paper_block(paper, summary=summary_lookup.get(paper.work_id))]

            reserve = LAST_MESSAGE_FOOTER_RESERVE if is_last_message else 0
            candidate = _message_text(header, blocks + [block])
            if len(candidate) <= max_length - reserve:
                blocks.append(block)
                index += 1
                continue
            break

        omitted_count = total_count - index
        if is_last_message and omitted_count:
            footer = [
                "",
                f"... and {omitted_count} more papers not shown. Narrow your watchlist or keywords.",
            ]
            while blocks and len(_message_text(header, blocks, footer=footer)) > max_length:
                blocks.pop()
                index -= 1
                omitted_count += 1
                footer[1] = f"... and {omitted_count} more papers not shown. Narrow your watchlist or keywords."
            messages.append(_message_text(header, blocks, footer=footer))
            break

        messages.append(_message_text(header, blocks))

        if not blocks:
            # A single block should already fit, but keep the fallback deterministic.
            messages[-1] = "\n".join(header + ["", "Digest too large to render."])
            break

    return messages


def _paper_block(paper: Paper, *, summary: str | None = None) -> list[str]:
    """Render the lines for a single paper within a digest."""
    lines = [
        f'<b><a href="{escape(paper.landing_url, quote=True)}">{escape(_truncate(paper.title, 180))}</a></b>',
    ]
    if summary:
        lines.append(f"💡 TL;DR: {escape(_truncate(summary, 260))}")
    lines.extend(
        [
            f"👥 <i>{escape(_truncate(paper.authors_summary, 160))}</i>",
            f"📅 {paper.publication_date.isoformat() if paper.publication_date else 'Unknown date'}",
        ]
    )
    if paper.matched_targets:
        matches = ", ".join(escape(target) for target in paper.matched_targets)
        lines.append(f"🏷 {matches}")
    return lines


def _message_header(total_count: int, *, continued: bool) -> str:
    """Render the digest title line."""
    if continued:
        return f"<b>📚 Paper radar - {total_count} new (continued)</b>"
    return f"<b>📚 Paper radar - {total_count} new</b>"


def _truncate(text: str, limit: int) -> str:
    """Truncate a string to ``limit`` characters with an ellipsis."""
    if len(text) <= limit:
        return text
    return text[: limit - 3].rstrip() + "..."


def _message_text(
    header: list[str],
    blocks: list[list[str]],
    *,
    footer: list[str] | None = None,
) -> str:
    """Join digest header, blocks, and an optional footer into one message."""
    lines = list(header)
    for block in blocks:
        lines.extend(block)
    if footer:
        lines.extend(footer)
    return "\n".join(lines)
