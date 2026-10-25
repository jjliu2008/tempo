"""Consumer-visible boundaries, history isolation, and agent scheduling."""

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

import httpx
import pytest
from google import genai
from google.genai import types
from pydantic import ValidationError

from app.core.config import Settings
from app.schemas.gemma import GemmaRequest, Message, MultiAgentRequest
from app.services.agent_orchestrator import AgentOrchestrator
from app.services.gemma import GemmaError, GemmaService

Handler = Callable[[httpx.Request], Awaitable[httpx.Response]]


def answer() -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "candidates": [
                {
                    "content": {"role": "model", "parts": [{"text": "Ready."}]},
                    "finishReason": "STOP",
                }
            ],
        },
    )


@asynccontextmanager
async def service(handler: Handler, *, limit: int = 2) -> AsyncIterator[GemmaService]:
    client = genai.Client(
        api_key="unit-test-key",
        vertexai=False,
        http_options=types.HttpOptions(
            httpx_async_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
            retry_options=types.HttpRetryOptions(attempts=1),
        ),
    )
    gemma = GemmaService(
        Settings(
            _env_file=None, GOOGLE_API_KEY="unit-test-key", GEMMA_MAX_CONCURRENT_REQUESTS=limit
        ),
        client=client,
    )
    try:
        yield gemma
    finally:
        await gemma.aclose()


@pytest.mark.parametrize(
    "fields",
    [
        {"prompt": "  "},
        {"prompt": "hello", "temperature": -0.1},
        {"prompt": "hello", "temperature": 2.1},
        {"prompt": "hello", "max_output_tokens": 0},
        {"prompt": "hello", "max_output_tokens": 32769},
        {"prompt": "hello", "max_output_tokens": True},
        {"prompt": "hello", "history": [{"role": "model", "content": "orphan"}]},
        {"prompt": "hello", "history": [{"role": "user", "content": "unfinished"}]},
        {
            "prompt": "hello",
            "history": [
                {"role": "user", "content": "hi"},
                {"role": "user", "content": "not a model turn"},
            ],
        },
        {
            "prompt": "hello",
            "history": [
                {"role": "user", "content": "hi"},
                {"role": "model", "content": "reply", "context": {"injected": True}},
            ],
        },
    ],
)
def test_rejects_unusable_conversations(fields: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        GemmaRequest.model_validate(fields)


@pytest.mark.parametrize(
    "agents",
    [
        [],
        [{"id": "a", "prompt": "one"}, {"id": "a", "prompt": "two"}],
        [{"id": "a", "prompt": "one", "depends_on": ["missing"]}],
        [{"id": "a", "prompt": "one", "depends_on": ["a"]}],
        [
            {"id": "a", "prompt": "one", "depends_on": ["b"]},
            {"id": "b", "prompt": "two", "depends_on": ["a"]},
        ],
        [
            {"id": "a", "prompt": "one", "depends_on": ["b", "b"]},
            {"id": "b", "prompt": "two"},
        ],
    ],
)
def test_rejects_invalid_agent_graphs(agents: list[dict[str, object]]) -> None:
    with pytest.raises(ValidationError):
        MultiAgentRequest.model_validate({"agents": agents})


async def test_history_preserves_turn_context_without_cross_request_leaks() -> None:
    async def respond(_: httpx.Request) -> httpx.Response:
        return answer()

    request = GemmaRequest(prompt="Remember this.", context={"private": ["one", {"two": 2}]})
    async with service(respond) as gemma:
        first = await gemma.generate(request)
        second, separate = await asyncio.gather(
            gemma.generate(GemmaRequest(prompt="Recall it.", history=first.history)),
            gemma.generate(GemmaRequest(prompt="Unrelated.")),
        )
    assert second.history[0].context == {"private": ["one", {"two": 2}]}
    assert [m.role for m in second.history] == ["user", "model", "user", "model"]
    assert [m.content for m in separate.history] == ["Unrelated.", "Ready."]
    assert all(m.context is None for m in separate.history)
    assert request.history == []
    assert [m.content for m in first.history] == ["Remember this.", "Ready."]


async def test_shared_service_bounds_concurrent_provider_calls() -> None:
    active = 0
    peak = 0
    first_pair = asyncio.Event()
    release = asyncio.Event()

    async def respond(_: httpx.Request) -> httpx.Response:
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        if active == 2:
            first_pair.set()
        await release.wait()
        active -= 1
        return answer()

    async with service(respond, limit=2) as gemma:
        tasks = [asyncio.create_task(gemma.generate(GemmaRequest(prompt=str(i)))) for i in range(5)]
        try:
            await asyncio.wait_for(first_pair.wait(), timeout=2)
            assert active == 2
            release.set()
            await asyncio.wait_for(asyncio.gather(*tasks), timeout=2)
        finally:
            release.set()
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
    assert peak == 2
    assert active == 0


async def test_agents_wait_for_dependencies_and_run_independent_roots_concurrently() -> None:
    import json

    roots_started: set[str] = set()
    roots_finished: set[str] = set()
    both_roots = asyncio.Event()

    async def respond(request: httpx.Request) -> httpx.Response:
        prompt = json.loads(request.content)["contents"][-1]["parts"][-1]["text"]
        if prompt in ("root-a", "root-b"):
            roots_started.add(prompt)
            if len(roots_started) == 2:
                both_roots.set()
            await asyncio.wait_for(both_roots.wait(), timeout=2)
            roots_finished.add(prompt)
        else:
            assert prompt == "combine"
            assert roots_finished == {"root-a", "root-b"}
        return answer()

    graph = MultiAgentRequest.model_validate(
        {
            "agents": [
                {"id": "combine", "prompt": "combine", "depends_on": ["a", "b"]},
                {"id": "a", "prompt": "root-a"},
                {"id": "b", "prompt": "root-b"},
            ]
        }
    )
    async with service(respond) as gemma:
        result = await asyncio.wait_for(AgentOrchestrator(gemma).run_agents(graph), timeout=3)
    assert [agent.id for agent in result.results] == ["combine", "a", "b"]
    assert graph.agents[0].context is None
    assert graph.agents[0].history == []


async def test_failed_agent_cancels_running_sibling_and_never_starts_dependent() -> None:
    import json

    sibling_started = asyncio.Event()
    sibling_cancelled = asyncio.Event()
    started: set[str] = set()

    async def respond(request: httpx.Request) -> httpx.Response:
        prompt = json.loads(request.content)["contents"][-1]["parts"][-1]["text"]
        started.add(prompt)
        if prompt == "fail":
            await sibling_started.wait()
            return httpx.Response(429, json={"error": {"code": 429, "message": "quota"}})
        if prompt == "sibling":
            sibling_started.set()
            try:
                await asyncio.Event().wait()
            finally:
                sibling_cancelled.set()
        pytest.fail("A dependent ran after its prerequisite failed")

    graph = MultiAgentRequest.model_validate(
        {
            "agents": [
                {"id": "dependent", "prompt": "dependent", "depends_on": ["a"]},
                {"id": "a", "prompt": "fail"},
                {"id": "b", "prompt": "sibling"},
            ]
        }
    )
    async with service(respond) as gemma:
        with pytest.raises(GemmaError) as failure:
            await asyncio.wait_for(AgentOrchestrator(gemma).run_agents(graph), timeout=3)
        assert failure.value.kind == "rate_limited"
        assert sibling_cancelled.is_set()
        # Cancellation/failure must release all shared slots for the next request.
        with pytest.raises(GemmaError) as subsequent:
            await asyncio.wait_for(gemma.generate(GemmaRequest(prompt="fail")), timeout=2)
        assert subsequent.value.kind == "rate_limited"
    assert started == {"fail", "sibling"}


@pytest.mark.parametrize(
    ("payload", "kind"),
    [
        ({"promptFeedback": {"blockReason": "SAFETY"}}, "blocked"),
        ({"candidates": []}, "provider"),
        ({"candidates": [{"finishReason": "SAFETY"}]}, "blocked"),
        ({"candidates": [{"content": {"parts": [{"text": " "}]}}]}, "provider"),
    ],
)
async def test_no_success_for_blocked_or_empty_answers(
    payload: dict[str, object], kind: str
) -> None:
    async def respond(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload)

    async with service(respond) as gemma:
        with pytest.raises(GemmaError) as failure:
            await gemma.generate(GemmaRequest(prompt="hello"))
    assert failure.value.kind == kind


async def test_thoughts_are_not_exposed_as_the_answer_or_in_history() -> None:
    async def respond(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "candidates": [
                    {
                        "content": {
                            "parts": [
                                {"text": "Internal reasoning", "thought": True},
                                {"text": "Public answer"},
                            ]
                        },
                        "finishReason": "MAX_TOKENS",
                    }
                ]
            },
        )

    async with service(respond) as gemma:
        result = await gemma.generate(GemmaRequest(prompt="hello"))
    assert result.text == "Public answer"
    assert result.history[-1] == Message(role="model", content="Public answer")
    assert result.finish_reason == "MAX_TOKENS"
