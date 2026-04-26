from __future__ import annotations

from datetime import date

from openalex_paper_bot.formatter import build_digest, build_digest_messages
from openalex_paper_bot.models import Paper


def test_build_digest_groups_by_primary_target_order() -> None:
    papers = [
        Paper(
            work_id="https://openalex.org/W1",
            title="A useful paper",
            publication_date=date(2026, 4, 3),
            landing_url="https://example.com/paper-1",
            authors_summary="Alice, Bob",
            matched_targets=["Meta", "Yann LeCun"],
        ),
        Paper(
            work_id="https://openalex.org/W2",
            title="Another paper",
            publication_date=date(2026, 4, 2),
            landing_url="https://example.com/paper-2",
            authors_summary="Carol",
            matched_targets=["Shirley Ho"],
        ),
    ]

    digest = build_digest(
        papers,
        target_order=["Yann LeCun", "Shirley Ho", "Meta"],
    )

    assert digest.startswith("<b>📚 Paper radar - 2 new</b>")
    assert "\nYann LeCun\n" in digest
    assert "\nShirley Ho\n" in digest
    assert "🏷️ Matches: Yann LeCun, Meta" in digest
    assert '<b><a href="https://example.com/paper-1">A useful paper</a></b>' in digest
    assert "👥 <i>Alice, Bob</i>" in digest
    assert "📅 2026-04-03" in digest


def test_build_digest_escapes_html_in_clickable_titles() -> None:
    paper = Paper(
        work_id="https://openalex.org/W1",
        title='A <dangerous> "paper" & friends',
        publication_date=date(2026, 4, 3),
        landing_url='https://example.com/paper?x=1&y="2"',
        authors_summary="Alice, Bob",
        matched_targets=["Meta & Labs", "Other <Team>"],
    )

    digest = build_digest([paper], target_order=["Meta & Labs", "Other <Team>"])

    assert (
        '<b><a href="https://example.com/paper?x=1&amp;y=&quot;2&quot;">'
        "A &lt;dangerous&gt; &quot;paper&quot; &amp; friends"
        "</a></b>"
    ) in digest
    assert "\nMeta &amp; Labs\n" in digest
    assert "🏷️ Matches: Meta &amp; Labs, Other &lt;Team&gt;" in digest


def test_build_digest_renders_escaped_summary_after_title() -> None:
    paper = Paper(
        work_id="https://openalex.org/W1",
        title="A useful paper",
        publication_date=date(2026, 4, 3),
        landing_url="https://example.com/paper",
        authors_summary="Alice, Bob",
        matched_targets=["Meta"],
    )

    digest = build_digest(
        [paper],
        target_order=["Meta"],
        summaries={"https://openalex.org/W1": "Uses <agents> & retrieval."},
    )

    assert '<b><a href="https://example.com/paper">A useful paper</a></b>' in digest
    assert "💡 TL;DR: Uses &lt;agents&gt; &amp; retrieval." in digest
    assert digest.index("💡 TL;DR") < digest.index("👥")


def test_build_digest_empty_message() -> None:
    assert build_digest([]) == "No new matching papers."


def test_build_digest_reports_omitted_papers_when_truncated() -> None:
    papers = [
        Paper(
            work_id=f"https://openalex.org/W{index}",
            title=f"Paper {index} with a somewhat long title for truncation behavior",
            publication_date=date(2026, 4, 3),
            landing_url=f"https://example.com/paper-{index}",
            authors_summary="Alice, Bob, Carol",
            matched_targets=["Meta"],
        )
        for index in range(1, 8)
    ]

    messages = build_digest_messages(
        papers,
        target_order=["Meta"],
        max_length=320,
        max_messages=1,
    )

    assert len(messages) == 1
    assert "<b>📚 Paper radar - 7 new</b>" in messages[0]
    assert "more papers not shown" in messages[0]


def test_build_digest_marks_continued_messages() -> None:
    papers = [
        Paper(
            work_id=f"https://openalex.org/W{index}",
            title=f"Paper {index} with a title that makes the digest split",
            publication_date=date(2026, 4, 3),
            landing_url=f"https://example.com/paper-{index}",
            authors_summary="Alice, Bob, Carol",
            matched_targets=["Meta"],
        )
        for index in range(1, 5)
    ]

    messages = build_digest_messages(
        papers,
        target_order=["Meta"],
        max_length=260,
        max_messages=3,
    )

    assert len(messages) > 1
    assert messages[0].startswith("<b>📚 Paper radar - 4 new</b>")
    assert messages[1].startswith("<b>📚 Paper radar - 4 new (continued)</b>")
