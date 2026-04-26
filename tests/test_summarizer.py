from __future__ import annotations

from openalex_paper_bot.models import Paper, SummaryOptions
from openalex_paper_bot.summarizer import build_paper_summaries


def test_build_paper_summaries_returns_empty_when_disabled() -> None:
    paper = Paper(
        work_id="https://openalex.org/W1",
        title="A useful paper",
        landing_url="https://example.com/paper",
        abstract="This paper has an abstract.",
        authors_summary="Alice",
    )

    assert build_paper_summaries([paper], SummaryOptions(enabled=False)) == {}


def test_fake_summarizer_uses_first_abstract_sentence() -> None:
    paper = Paper(
        work_id="https://openalex.org/W1",
        title="A useful paper",
        landing_url="https://example.com/paper",
        abstract="This paper introduces a benchmark. It also evaluates several baselines.",
        authors_summary="Alice",
    )
    paper_without_abstract = Paper(
        work_id="https://openalex.org/W2",
        title="Another paper",
        landing_url="https://example.com/other",
        authors_summary="Bob",
    )

    summaries = build_paper_summaries(
        [paper, paper_without_abstract],
        SummaryOptions(enabled=True, provider="fake"),
    )

    assert summaries == {"https://openalex.org/W1": "This paper introduces a benchmark."}
