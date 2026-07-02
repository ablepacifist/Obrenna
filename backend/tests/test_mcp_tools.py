"""Tests for MCP tools implementation."""
import asyncio
import pytest

from app.mcp.tools import (
    acall_tool,
    call_tool,
    list_tools,
    tool_calculator,
    tool_get_time,
    tool_file_read,
    tool_web_search,
    tool_get_location,
    TOOL_DEFS,
    TOOLS,
)


class TestListTools:
    """Test MCP tool list endpoint."""

    def test_returns_five_tools(self):
        tools = list_tools()
        names = [t["name"] for t in tools]
        assert len(names) == 5
        assert "get_time" in names
        assert "calculator" in names
        assert "file_read" in names
        assert "web_search" in names
        assert "get_location" in names

    def test_tool_has_schema(self):
        tools = list_tools()
        for t in tools:
            assert "name" in t
            assert "description" in t
            assert "inputSchema" in t

    def test_calculator_rejects_eval(self):
        """Verify calculator tool description mentions no eval."""
        calc = next(t for t in list_tools() if t["name"] == "calculator")
        assert "eval" in calc["description"].lower()


class TestCalculator:
    """Test calculator tool - sandboxed expression evaluation."""

    def test_addition(self):
        result = tool_calculator({"expression": "2+3"})
        assert result["result"] == 5

    def test_subtraction(self):
        result = tool_calculator({"expression": "10-4"})
        assert result["result"] == 6

    def test_multiplication(self):
        result = tool_calculator({"expression": "3*7"})
        assert result["result"] == 21

    def test_division(self):
        result = tool_calculator({"expression": "15/4"})
        assert abs(result["result"] - 3.75) < 0.001

    def test_parentheses(self):
        result = tool_calculator({"expression": "(2+3)*4"})
        assert result["result"] == 20

    def test_exponentiation(self):
        result = tool_calculator({"expression": "2**3"})
        assert result["result"] == 8

    def test_modulo(self):
        result = tool_calculator({"expression": "10%3"})
        assert result["result"] == 1

    def test_decimal(self):
        result = tool_calculator({"expression": "1.5+2.5"})
        assert result["result"] == 4.0

    def test_rejects_code_execution(self):
        """Calculator must reject attempts at code execution."""
        result = tool_calculator({"expression": "__import__('os').system('ls')"})
        assert result["error"] is True

    def test_rejects_function_call(self):
        result = tool_calculator({"expression": "print(1)"})
        assert result["error"] is True

    def test_rejects_semicolon(self):
        result = tool_calculator({"expression": "1;2"})
        assert result["error"] is True

    def test_division_by_zero(self):
        result = tool_calculator({"expression": "1/0"})
        assert result["error"] is True

    def test_empty_expression(self):
        result = tool_calculator({"expression": ""})
        # Should not crash; may return error or 0
        assert "error" in result or "result" in result

    def test_negative_numbers(self):
        result = tool_calculator({"expression": "-3+5"})
        assert result["result"] == 2

    def test_complex_expression(self):
        result = tool_calculator({"expression": "((10+5)*2)-3**2"})
        # (15*2) - 9 = 30 - 9 = 21
        assert result["result"] == 21

    def test_rejects_trailing_tokens(self):
        """MED-014: before the fix, "2 2" silently returned 2 — the parser
        never checked whether all tokens were consumed."""
        result = tool_calculator({"expression": "2 2"})
        assert result["error"] is True

    def test_rejects_trailing_tokens_after_parens(self):
        result = tool_calculator({"expression": "(1+1)3"})
        assert result["error"] is True

    def test_rejects_trailing_operator_garbage(self):
        result = tool_calculator({"expression": "3)3"})
        assert result["error"] is True

    def test_rejects_oversized_exponent(self):
        """MED-014: an unbounded exponent (e.g. 9**9**9) can hang the
        process computing/allocating an astronomically large int/float."""
        result = tool_calculator({"expression": "2**99999"})
        assert result["error"] is True

    def test_allows_reasonable_exponent(self):
        result = tool_calculator({"expression": "2**10"})
        assert result["result"] == 1024


class TestGetTime:
    """Test get_time tool."""

    def test_returns_time(self):
        result = tool_get_time({})
        assert "time" in result
        assert "timezone_offset" in result
        assert "unix_timestamp" in result
        assert "iso_datetime" in result
        assert "human_readable" in result
        assert "date" in result
        assert "local_time" in result
        assert "weekday" in result
        assert "year" in result
        assert "timezone" in result
        assert "utc_offset" in result

    def test_unix_timestamp_is_int(self):
        result = tool_get_time({})
        assert isinstance(result["unix_timestamp"], int)

    def test_time_is_iso_format(self):
        result = tool_get_time({})
        # Should be parseable as ISO format
        from datetime import datetime
        datetime.fromisoformat(result["time"])
        datetime.fromisoformat(result["iso_datetime"])

    def test_year_matches_iso_datetime(self):
        result = tool_get_time({})
        from datetime import datetime
        parsed = datetime.fromisoformat(result["iso_datetime"])
        assert result["year"] == parsed.year


class TestWebSearch:
    """Test web_search tool."""

    def test_requires_query(self):
        result = asyncio.run(tool_web_search({}))
        assert result["error"] is True

    def test_returns_snippets(self):
        result = asyncio.run(tool_web_search({"query": "test query"}))
        assert "results" in result
        assert isinstance(result["results"], list)

    def test_result_has_url(self):
        result = asyncio.run(tool_web_search({"query": "test"}))
        if result["results"]:
            assert "url" in result["results"][0]

    @pytest.mark.asyncio
    async def test_async_web_search(self):
        result = await acall_tool("web_search", {"query": "test async query"})
        assert "results" in result
        assert "query" in result
        assert isinstance(result["results"], list)

    @pytest.mark.asyncio
    async def test_async_web_search_requires_query(self):
        result = await acall_tool("web_search", {})
        assert result["error"] is True


class TestCallToolAsync:
    """Test async call_tool variants."""

    @pytest.mark.asyncio
    async def test_acall_tool_sync_handler(self):
        result = await acall_tool("get_time", {})
        assert "time" in result

    @pytest.mark.asyncio
    async def test_acall_tool_async_handler(self):
        result = await acall_tool("web_search", {"query": "test"})
        assert isinstance(result, dict)

    def test_call_tool_sync_handler(self):
        result = call_tool("calculator", {"expression": "2+2"})
        assert result["result"] == 4

    def test_call_tool_async_handler_without_existing_loop(self, monkeypatch):
        async def async_handler(args):
            return {"ok": True, "value": args["value"]}

        monkeypatch.setitem(TOOLS, "test_async", async_handler)

        result = call_tool("test_async", {"value": 7})

        assert result == {"ok": True, "value": 7}


class TestGetLocation:
    """Test get_location tool."""

    def test_returns_unavailable_in_phase1(self):
        result = tool_get_location({})
        assert result["status"] == "unavailable"


class TestFileRead:
    """Test file_read tool."""

    def test_requires_file_id_or_path(self):
        result = tool_file_read({})
        assert result["error"] is True

    def test_rejects_arbitrary_path(self):
        result = tool_file_read({"path": "/etc/passwd"})
        assert result["error"] is True


class TestToolDefinitions:
    """Test tool definitions."""

    def test_all_tools_defined(self):
        tools = list_tools()
        names = [t["name"] for t in tools]
        assert len(names) == 5

    def test_tool_schemas_present(self):
        tools = list_tools()
        for t in tools:
            assert "inputSchema" in t
            assert "properties" in t["inputSchema"]

    def test_tool_descriptions_present(self):
        tools = list_tools()
        for t in tools:
            assert t["description"].strip() and len(t["description"]) > 10


class TestToolEvents:
    """Test tool event types and factories."""

    def test_event_types_defined(self):
        from app.agent.events import (
            EVENT_TYPE_TOOL_CALL,
            EVENT_TYPE_TOOL_RESULT,
            EVENT_TYPE_TOOL_PROGRESS,
        )
        assert EVENT_TYPE_TOOL_CALL == "tool_call"
        assert EVENT_TYPE_TOOL_RESULT == "tool_result"
        assert EVENT_TYPE_TOOL_PROGRESS == "tool_progress"

    def test_tool_call_event(self):
        from app.agent.events import tool_call_event
        event = tool_call_event("chat1", "web_search", "call_001", {"query": "test"})
        assert event.type == "tool_call"
        assert event.payload["tool_name"] == "web_search"
        assert event.payload["call_id"] == "call_001"
        assert event.payload["arguments"]["query"] == "test"

    def test_tool_result_event(self):
        from app.agent.events import tool_result_event
        event = tool_result_event("chat1", "web_search", "call_001", '{"results": []}')
        assert event.type == "tool_result"
        assert "results" in event.payload["result"]

    def test_tool_progress_event(self):
        from app.agent.events import tool_progress_event
        event = tool_progress_event("chat1", "web_search", "running", "Searching...")
        assert event.type == "tool_progress"
        assert event.payload["status"] == "running"

    def test_valid_event_types_includes_tool_types(self):
        from app.agent.events import VALID_EVENT_TYPES
        assert "tool_call" in VALID_EVENT_TYPES
        assert "tool_result" in VALID_EVENT_TYPES
        assert "tool_progress" in VALID_EVENT_TYPES
