"""Regression tests for the observed orchestration failure: turn 1 (math)
answered, then turn 2 ("latest AI news") replayed the previous math answer.

Root causes covered here:
1. History duplication — the just-persisted current user message was included
   in ``previous_messages`` AND appended again as the active task, and the
   memory recency band injected the previous assistant answer a second time
   as system context. Small orchestrators replayed the duplicated answer.
2. No deterministic routing — math / current-news / time asks depended
   entirely on a small model choosing tools; news with web disabled had no
   honest refusal path.
3. Literal ``<think>`` blocks in streamed content were never stripped.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.agent.runtime import (
    ResolvedPlan,
    WEB_DISABLED_NEWS_ANSWER,
    _build_orchestrator_messages,
    classify_deterministic_route,
    extract_math_expression,
    is_current_news_query,
    orchestrate_turn,
)
from app.db import Base
from app.mcp.tools import TOOL_DEFS, call_tool
from app.model_runtime.config import RuntimeConfig
from app.model_runtime.streaming import ThinkTagStreamFilter, chat_completion_stream
from app.models import AppSettings, Chat, ChatMessage, ModelEndpoint
from app.schemas.api import ChatRequest
from app.services.memory import MemoryContext, assemble_context


MATH_PROMPT = "sure do 6*25+90 all divided by 4 give me the anser to the nearest decimal"
NEWS_PROMPT = "Can you tell me the latest in AI related news"
MATH_ANSWER = "Solution\nProblem: 6 x 25 + 90 / 4\nAnswer 172.5"


def _config() -> RuntimeConfig:
    return RuntimeConfig(
        provider="openai_compatible",
        base_url="http://localhost:11434/v1",
        models={"orchestrator": "qwen3.5:4b"},
    )


def _plan(mode: str = "openai_native") -> ResolvedPlan:
    return ResolvedPlan({"orchestrator": {"model": "qwen3.5:4b", "tool_call_mode": mode}})


class _StubMemory:
    def to_static_messages(self):
        return []

    def to_dynamic_messages(self):
        return []


# ── 4. Calculator routing / NL normalisation ─────────────────────────────────


class TestMathExpressionNormalisation:
    def test_all_divided_by_parenthesises_whole_expression(self):
        # "all divided by 4" means (6*25+90)/4 = 60.0, never 6*25 + 90/4 = 172.5.
        assert extract_math_expression(MATH_PROMPT) == "(6*25+90)/4"

    def test_plain_expression_extracted(self):
        assert extract_math_expression("what is (6*25+90)/4?") == "(6*25+90)/4"

    def test_word_operators_normalised(self):
        expr = extract_math_expression("calculate 6 times 25 plus 90")
        assert expr is not None
        result = call_tool("calculator", {"expression": expr})
        assert result["result"] == 240

    def test_news_prompt_is_not_math(self):
        assert extract_math_expression(NEWS_PROMPT) is None

    def test_time_range_prose_is_not_math(self):
        # "2-3pm" must not be silently computed as 2-3.
        assert extract_math_expression("can we meet between 2-3pm tomorrow?") is None

    def test_normalised_expression_evaluates_to_60(self):
        expr = extract_math_expression(MATH_PROMPT)
        result = call_tool("calculator", {"expression": expr})
        assert result["result"] == 60.0


class TestDeterministicRouting:
    def test_math_routes_to_calculator(self):
        route = classify_deterministic_route(MATH_PROMPT, web_search_enabled=False)
        assert route == ("calculator", {"expression": "(6*25+90)/4"})

    def test_news_routes_to_web_search_when_enabled(self):
        route = classify_deterministic_route(NEWS_PROMPT, web_search_enabled=True)
        assert route == ("web_search", {"query": NEWS_PROMPT})

    def test_news_with_web_disabled_routes_to_refusal(self):
        route = classify_deterministic_route(NEWS_PROMPT, web_search_enabled=False)
        assert route == ("web_search_disabled", {})

    def test_time_query_routes_to_get_time(self):
        route = classify_deterministic_route("what time is it?", web_search_enabled=False)
        assert route == ("get_time", {})

    def test_plain_chat_is_not_forced(self):
        assert classify_deterministic_route("tell me a joke", web_search_enabled=True) is None
        assert is_current_news_query("tell me a joke") is False


# ── 2/3. Current-news routing & web-disabled behaviour ───────────────────────


class TestWebDisabledNews:
    @pytest.mark.asyncio
    async def test_news_with_web_disabled_answers_honestly_without_model(self, monkeypatch):
        from app.agent import runtime as rt

        monkeypatch.setattr(rt, "assemble_context", lambda *a, **k: _StubMemory())

        async def fail_stream(*args, **kwargs):
            raise AssertionError("model must not be called when web is disabled for a news ask")
            yield  # pragma: no cover

        monkeypatch.setattr(rt, "chat_completion_stream", fail_stream)

        events = [e async for e in orchestrate_turn(
            NEWS_PROMPT, "chat-web-off", None, _config(), _plan(),
            web_search=False, workers_enabled=False,
            previous_messages=[
                {"role": "user", "content": MATH_PROMPT},
                {"role": "assistant", "content": MATH_ANSWER},
            ],
        )]

        tokens = "".join(e.payload.get("text", "") for e in events if e.type == "token")
        assert tokens == WEB_DISABLED_NEWS_ANSWER
        assert "172.5" not in tokens  # never replay the previous answer
        assert any(e.type == "done" for e in events)


class TestNewsRoutesToWebSearch:
    @pytest.mark.asyncio
    async def test_web_search_forced_before_model(self, monkeypatch):
        from app.agent import runtime as rt
        import app.mcp.tools as mcp_tools

        monkeypatch.setattr(rt, "assemble_context", lambda *a, **k: _StubMemory())

        tool_calls_made = []

        async def fake_acall(name, args):
            tool_calls_made.append((name, args))
            return {"results": [{"title": "AI headline", "snippet": "Big model news.",
                                 "url": "https://example.test/ai"}]}

        monkeypatch.setattr(mcp_tools, "acall_tool", fake_acall)

        captured = []

        async def fake_stream(config, messages, **kwargs):
            captured.append(messages)
            yield {"type": "token", "content": "Here is the latest AI news."}

        monkeypatch.setattr(rt, "chat_completion_stream", fake_stream)

        events = [e async for e in orchestrate_turn(
            NEWS_PROMPT, "chat-news", None, _config(), _plan(),
            web_search=True, workers_enabled=False,
        )]

        # web_search executed deterministically before the first model pass.
        assert tool_calls_made and tool_calls_made[0][0] == "web_search"
        assert tool_calls_made[0][1]["query"] == NEWS_PROMPT
        types = [e.type for e in events]
        assert "tool_call" in types and "tool_result" in types
        # The model saw the tool evidence (native mode: role:"tool" message).
        round1 = captured[0]
        assert any(m.get("role") == "tool" and "AI headline" in (m.get("content") or "")
                   for m in round1)
        tokens = "".join(e.payload.get("text", "") for e in events if e.type == "token")
        assert tokens == "Here is the latest AI news."


class TestCalculatorForcedRoute:
    @pytest.mark.asyncio
    async def test_math_prompt_executes_calculator_with_preferred_parse(self, monkeypatch):
        from app.agent import runtime as rt

        monkeypatch.setattr(rt, "assemble_context", lambda *a, **k: _StubMemory())

        captured = []

        async def fake_stream(config, messages, **kwargs):
            captured.append(messages)
            yield {"type": "token", "content": "The answer is 60.0."}

        monkeypatch.setattr(rt, "chat_completion_stream", fake_stream)

        # Real calculator tool via the real dev-mode MCP transport.
        events = [e async for e in orchestrate_turn(
            MATH_PROMPT, "chat-math", None, _config(), _plan(),
            web_search=False, workers_enabled=False,
        )]

        result_events = [e for e in events if e.type == "tool_result"]
        assert result_events and result_events[0].payload["tool_name"] == "calculator"
        assert "60.0" in result_events[0].payload["result"]
        assert "172.5" not in result_events[0].payload["result"]
        tokens = "".join(e.payload.get("text", "") for e in events if e.type == "token")
        assert "60.0" in tokens


# ── 1. Sequential-turn isolation (the observed failure) ─────────────────────


class TestSequentialTurnIsolation:
    @pytest.mark.asyncio
    async def test_news_turn_after_math_turn_does_not_replay_math(self, monkeypatch):
        from app.agent import runtime as rt
        import app.mcp.tools as mcp_tools

        monkeypatch.setattr(rt, "assemble_context", lambda *a, **k: _StubMemory())

        async def fake_acall(name, args):
            assert name == "web_search"
            return {"results": [{"title": "AI headline", "snippet": "Big model news.",
                                 "url": "https://example.test/ai"}]}

        monkeypatch.setattr(mcp_tools, "acall_tool", fake_acall)

        captured = []

        async def fake_stream(config, messages, **kwargs):
            captured.append(messages)
            yield {"type": "token", "content": "Fresh AI news summary."}

        monkeypatch.setattr(rt, "chat_completion_stream", fake_stream)

        previous = [
            {"role": "user", "content": MATH_PROMPT},
            {"role": "assistant", "content": MATH_ANSWER},
        ]
        events = [e async for e in orchestrate_turn(
            NEWS_PROMPT, "chat-seq", None, _config(), _plan(),
            web_search=True, workers_enabled=False,
            previous_messages=previous,
        )]

        round1 = captured[0]
        contents = [(m.get("content") or "") for m in round1]
        # 6. Prompt assembly: the latest user message appears exactly once...
        assert sum(1 for c in contents if c == NEWS_PROMPT) == 1
        # ...and the previous assistant answer is history only (exactly once,
        # as an assistant turn — not system context, not a prefill).
        assert sum(1 for c in contents if MATH_ANSWER in c) == 1
        math_idx = next(i for i, m in enumerate(round1)
                        if MATH_ANSWER in (m.get("content") or ""))
        assert round1[math_idx]["role"] == "assistant"
        # No assistant prefill: the sequence must not end with a content-bearing
        # assistant message.
        last = round1[-1]
        assert not (last.get("role") == "assistant" and last.get("content"))

        tokens = "".join(e.payload.get("text", "") for e in events if e.type == "token")
        assert "172.5" not in tokens
        assert tokens == "Fresh AI news summary."


class TestPromptAssemblyNoDuplicateActiveTask:
    def test_latest_user_message_exactly_once_and_last(self):
        msgs = _build_orchestrator_messages(
            user_message=NEWS_PROMPT,
            static_parts=MemoryContext().to_static_messages(),
            dynamic_parts=[],
            evidence_summary="",
            previous_messages=[
                {"role": "user", "content": MATH_PROMPT},
                {"role": "assistant", "content": MATH_ANSWER},
            ],
            tool_call_mode="openai_native",
            allowed_tools=None,
        )
        assert msgs[-1] == {"role": "user", "content": NEWS_PROMPT}
        assert sum(1 for m in msgs if m.get("content") == NEWS_PROMPT) == 1
        assert sum(1 for m in msgs if MATH_ANSWER in (m.get("content") or "")) == 1


class TestHistoryExcludesCurrentUserMessage:
    """chat.py used to query the last 10 messages AFTER persisting the current
    user message, so the active task appeared twice in the prompt."""

    @pytest.fixture
    def db(self):
        eng = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
        Base.metadata.create_all(eng)
        session = sessionmaker(bind=eng)()
        session.add(AppSettings(id=1, workers_enabled=False))
        session.add(ModelEndpoint(
            id=1, provider="openai_compatible", base_url="http://localhost:11434/v1",
            models={"orchestrator": "qwen3.5:4b"},
        ))
        session.add(Chat(id="chat-hist", title="History test"))
        session.commit()
        return session

    def test_previous_messages_exclude_the_active_user_message(self, monkeypatch, db):
        from app.routers import chat as chat_router

        t0 = datetime.now(timezone.utc)
        db.add(ChatMessage(id="u1", chat_id="chat-hist", role="user",
                           text=MATH_PROMPT, created_at=t0))
        db.add(ChatMessage(id="a1", chat_id="chat-hist", role="assistant",
                           text=MATH_ANSWER, created_at=t0 + timedelta(seconds=1)))
        user_msg = ChatMessage(id="u2", chat_id="chat-hist", role="user",
                               text=NEWS_PROMPT, created_at=t0 + timedelta(seconds=2))
        db.add(user_msg)
        db.commit()

        seen_kwargs = {}

        async def fake_orchestrate_turn(*args, **kwargs):
            seen_kwargs.update(kwargs)
            from app.agent.events import StreamEvent
            yield StreamEvent(chat_id="chat-hist", type="token", payload={"text": "ok"})

        monkeypatch.setattr(chat_router, "orchestrate_turn", fake_orchestrate_turn)
        monkeypatch.setattr(
            chat_router, "_get_hardware_plan",
            lambda db, workers_enabled=True: {
                "path": "fallback", "ctx": 8192, "helper_count": 0,
                "orchestrator": {"model": "qwen3.5:4b"}, "summarizer": {}, "utility": {},
            },
        )

        chat = db.get(Chat, "chat-hist")
        payload = ChatRequest(chat_id="chat-hist", message=NEWS_PROMPT)
        chat_router._handle_normal_chat(db, chat, user_msg, payload,
                                        assistant_message_id="asst-hist-1")

        prev = seen_kwargs["previous_messages"]
        assert [m["role"] for m in prev] == ["user", "assistant"]
        assert prev[0]["content"] == MATH_PROMPT
        assert prev[1]["content"] == MATH_ANSWER
        assert all(m["content"] != NEWS_PROMPT for m in prev)


# ── 5. Stream isolation: distinct assistant message ids per turn ────────────


class TestStreamIsolation:
    @pytest.mark.asyncio
    async def test_two_turns_stream_into_distinct_message_ids(self, monkeypatch):
        from app.agent import runtime as rt

        monkeypatch.setattr(rt, "assemble_context", lambda *a, **k: _StubMemory())

        async def fake_stream(config, messages, **kwargs):
            yield {"type": "token", "content": "answer"}

        monkeypatch.setattr(rt, "chat_completion_stream", fake_stream)

        async def run(msg_id):
            return [e async for e in orchestrate_turn(
                "hello", "chat-stream", None, _config(), _plan(),
                assistant_message_id=msg_id, workers_enabled=False,
            )]

        events1 = await run("msg-turn-1")
        events2 = await run("msg-turn-2")

        for events, expected in ((events1, "msg-turn-1"), (events2, "msg-turn-2")):
            stream_ids = {e.message_id for e in events if e.type in ("token", "done")}
            assert stream_ids == {expected}


# ── 7. Tool schema validation ────────────────────────────────────────────────


class TestToolSchemas:
    @pytest.mark.parametrize("name", ["web_search", "calculator", "get_time",
                                      "file_read", "get_location"])
    def test_tool_has_valid_non_empty_schema(self, name):
        tdef = next(t for t in TOOL_DEFS if t["name"] == name)
        schema = tdef.get("inputSchema")
        assert isinstance(schema, dict) and schema, f"{name} must carry an inputSchema"
        assert schema.get("type") == "object"
        assert isinstance(schema.get("properties"), dict)

    def test_required_args_declared(self):
        by_name = {t["name"]: t for t in TOOL_DEFS}
        assert by_name["web_search"]["inputSchema"]["required"] == ["query"]
        assert by_name["calculator"]["inputSchema"]["required"] == ["expression"]


# ── 8. <think> stripping ─────────────────────────────────────────────────────


class TestThinkStripping:
    def test_filter_splits_think_span_across_chunks(self):
        f = ThinkTagStreamFilter()
        visible, thinking = [], []
        for chunk in ["<thi", "nk>inter", "nal</thi", "nk>Final answer"]:
            v, t = f.feed(chunk)
            visible.append(v)
            thinking.append(t)
        v, t = f.flush()
        visible.append(v)
        thinking.append(t)
        assert "".join(visible) == "Final answer"
        assert "".join(thinking) == "internal"

    def test_unclosed_think_never_becomes_visible(self):
        f = ThinkTagStreamFilter()
        v1, t1 = f.feed("<think>still going")
        v2, t2 = f.flush()
        assert v1 + v2 == ""
        assert "still going" in (t1 + t2)

    @pytest.mark.asyncio
    async def test_stream_emits_think_as_thinking_delta_not_tokens(self, monkeypatch):
        captured: dict = {}
        lines = [
            'data: ' + json.dumps({"choices": [{"delta": {"content": "<think>internal</think>Final answer"}}]}),
            "data: [DONE]",
        ]

        class FakeResponse:
            status_code = 200

            def raise_for_status(self):
                pass

            async def aiter_lines(self):
                for line in lines:
                    yield line

        class FakeClient:
            def __init__(self, *args, **kwargs):
                pass

            def stream(self, method, url, **kwargs):
                captured.update(kwargs.get("json", {}))

                class _CM:
                    async def __aenter__(self):
                        return FakeResponse()

                    async def __aexit__(self, *a):
                        return False

                return _CM()

        monkeypatch.setattr(httpx, "AsyncClient", FakeClient)

        events = [e async for e in chat_completion_stream(
            _config(), [{"role": "user", "content": "hi"}], model="qwen3.5:4b",
        )]

        tokens = "".join(e["content"] for e in events if e["type"] == "token")
        thinking = "".join(e["content"] for e in events if e["type"] == "thinking_delta")
        assert tokens == "Final answer"
        assert "<think>" not in tokens
        assert thinking == "internal"


# ── 9. Memory leakage guard ──────────────────────────────────────────────────


class TestMemoryRecencyGuard:
    @pytest.fixture
    def db(self):
        eng = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
        Base.metadata.create_all(eng)
        session = sessionmaker(bind=eng)()
        session.add(Chat(id="chat-mem", title="Memory test"))
        session.add(ChatMessage(id="a1", chat_id="chat-mem", role="assistant",
                                text=MATH_ANSWER,
                                created_at=datetime.now(timezone.utc)))
        session.commit()
        return session

    def test_include_recency_false_drops_prior_answers(self, db):
        chat = db.get(Chat, "chat-mem")
        ctx = assemble_context(db, chat, NEWS_PROMPT,
                               memory_mode="exp0_recency_only",
                               include_recency=False)
        assert ctx.recency == []
        assert all(MATH_ANSWER not in m.get("content", "")
                   for m in ctx.to_dynamic_messages())

    def test_include_recency_true_keeps_recency_for_stateless_callers(self, db):
        chat = db.get(Chat, "chat-mem")
        ctx = assemble_context(db, chat, NEWS_PROMPT,
                               memory_mode="exp0_recency_only",
                               include_recency=True)
        assert ctx.recency, "recency-only mode must still work without previous_messages"

    def test_recency_band_is_labelled_non_authoritative(self):
        ctx = MemoryContext(recency=[{"role": "assistant", "text": MATH_ANSWER}])
        band = ctx.to_dynamic_messages()[0]["content"]
        assert "do not repeat" in band
        assert "latest user message" in band

    @pytest.mark.asyncio
    async def test_runtime_disables_recency_when_history_present(self, monkeypatch):
        from app.agent import runtime as rt

        seen = {}

        def fake_assemble(db, chat, user_message, **kwargs):
            seen.update(kwargs)
            return _StubMemory()

        monkeypatch.setattr(rt, "assemble_context", fake_assemble)

        async def fake_stream(config, messages, **kwargs):
            yield {"type": "token", "content": "ok"}

        monkeypatch.setattr(rt, "chat_completion_stream", fake_stream)

        async for _ in orchestrate_turn(
            "hello", "chat-rec", None, _config(), _plan(),
            workers_enabled=False,
            previous_messages=[{"role": "user", "content": "hi"},
                               {"role": "assistant", "content": "hello!"}],
        ):
            pass
        assert seen["include_recency"] is False

        seen.clear()
        async for _ in orchestrate_turn(
            "hello", "chat-rec2", None, _config(), _plan(),
            workers_enabled=False, previous_messages=[],
        ):
            pass
        assert seen["include_recency"] is True
