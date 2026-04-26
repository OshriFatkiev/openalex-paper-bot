from __future__ import annotations

import json

import httpx

from openalex_paper_bot.models import Paper, SummaryOptions
from openalex_paper_bot.summarizer import GitHubModelsSummarizer, _truncate, build_paper_summaries


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


def test_github_models_summarizer_posts_chat_completion_request() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": "TL;DR: Introduces a benchmark for evaluating agents.",
                        }
                    }
                ]
            },
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    summarizer = GitHubModelsSummarizer(
        token="test-token",
        model="openai/gpt-4.1-mini",
        max_chars=220,
        client=client,
    )
    paper = Paper(
        work_id="https://openalex.org/W1",
        title="A useful paper",
        landing_url="https://example.com/paper",
        abstract="This paper introduces a benchmark for evaluating agents.",
        authors_summary="Alice",
    )

    summaries = summarizer.summarize([paper])

    assert summaries == {"https://openalex.org/W1": "Introduces a benchmark for evaluating agents."}
    assert len(requests) == 1
    request = requests[0]
    assert str(request.url) == "https://models.github.ai/inference/chat/completions"
    assert request.headers["authorization"] == "Bearer test-token"
    body = json.loads(request.content)
    assert body["model"] == "openai/gpt-4.1-mini"
    assert body["temperature"] == 0
    assert body["messages"][0]["role"] == "system"
    assert "TL;DR" not in body["messages"][0]["content"]
    assert "TL;DR" not in body["messages"][1]["content"]
    assert "Return one compact sentence" in body["messages"][0]["content"]
    assert "one compact sentence" in body["messages"][1]["content"]
    assert "focused on the paper's key contribution" in body["messages"][1]["content"]
    assert "Use at most 14 words" in body["messages"][1]["content"]
    assert "Keep it under" not in body["messages"][1]["content"]
    assert "Title: A useful paper" in body["messages"][1]["content"]
    assert "This paper introduces a benchmark" in body["messages"][1]["content"]


def test_truncate_prefers_word_boundary_when_cutting_mid_word() -> None:
    summary = "Supervised learning keeps label-correlated nuisance sensitivities."

    assert _truncate(summary, 50) == "Supervised learning keeps label-correlated..."


def test_github_models_summarizer_skips_failed_requests() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, request=request)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    summarizer = GitHubModelsSummarizer(
        token="test-token",
        model="openai/gpt-4.1-mini",
        max_chars=220,
        client=client,
    )
    paper = Paper(
        work_id="https://openalex.org/W1",
        title="A useful paper",
        landing_url="https://example.com/paper",
        abstract="This paper has an abstract.",
        authors_summary="Alice",
    )

    assert summarizer.summarize([paper]) == {}


def test_build_paper_summaries_skips_github_models_without_token() -> None:
    paper = Paper(
        work_id="https://openalex.org/W1",
        title="A useful paper",
        landing_url="https://example.com/paper",
        abstract="This paper has an abstract.",
        authors_summary="Alice",
    )

    summaries = build_paper_summaries(
        [paper],
        SummaryOptions(enabled=True, provider="github_models"),
        github_models_token=None,
    )

    assert summaries == {}
