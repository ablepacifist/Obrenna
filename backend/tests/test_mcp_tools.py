"""Tests for MCP tools implementation."""
import pytest

from app.mcp.tools import (
    call_tool,
    list_tools,
    tool_calculator,
    tool_get_time,
    tool_file_read,
    tool_web_search,
    tool_get_location,
    TOOL_DEFS,
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


class TestGetTime:
    """Test get_time tool."""

    def test_returns_time(self):
        result = tool_get_time({})
        assert "time" in result
        assert "timezone_offset" in result
        assert "unix_timestamp" in result

    def test_unix_timestamp_is_int(self):
        result = tool_get_time({})
        assert isinstance(result["unix_timestamp"], int)

    def test_time_is_iso_format(self):
        result = tool_get_time({})
        # Should be parseable as ISO format
        from datetime import datetime
        datetime.fromisoformat(result["time"])


class TestWebSearch:
    """Test web_search tool."""

    def test_requires_query(self):
        result = tool_web_search({})
        assert result["error"] is True

    def test_returns_snippets(self):
        result = tool_web_search({"query": "test query"})
        assert "results" in result
        assert isinstance(result["results"], list)

    def test_result_has_url(self):
        result = tool_web_search({"query": "test"})
        if result["results"]:
            assert "url" in result["results"][0]


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
