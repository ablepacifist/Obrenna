"""Tests for tool invocation loop in agent runtime."""
import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agent.runtime import (
    handle_tool_calls,
    _format_tools_for_model,
    _get_allowed_tools_for_request,
    allowed_mcp_tools_config,
)
from app.mcp.client import MCPClient, InMemoryTransport


class TestToolCallHandling:
    """Test handle_tool_calls integration."""

    @pytest.mark.asyncio
    async def test_single_tool_call(self):
        transport = InMemoryTransport()
        transport.register_handler("tools/call", lambda p: {"result": 42})
        client = MCPClient(transport)
        await client.initialize()

        tool_calls = [
            {
                "id": "call_001",
                "type": "function",
                "function": {
                    "name": "calculator",
                    "arguments": {"expression": "6*7"},
                },
            }
        ]
        results = await handle_tool_calls(tool_calls, client)
        assert len(results) == 1
        assert results[0]["tool_call_id"] == "call_001"

    @pytest.mark.asyncio
    async def test_multiple_tool_calls(self):
        transport = InMemoryTransport()
        transport.register_handler("tools/call", lambda p: {"output": f"result for {p['name']}"})
        client = MCPClient(transport)
        await client.initialize()

        tool_calls = [
            {
                "id": "call_001",
                "type": "function",
                "function": {"name": "get_time", "arguments": {}},
            },
            {
                "id": "call_002",
                "type": "function",
                "function": {"name": "calculator", "arguments": {"expression": "1+1"}},
            },
        ]
        results = await handle_tool_calls(tool_calls, client)
        assert len(results) == 2

    @pytest.mark.asyncio
    async def test_unknown_tool_returns_error(self):
        transport = InMemoryTransport()
        transport.register_handler("tools/call", lambda p: {"content": [{"type": "text", "text": "Tool not found"}]})
        client = MCPClient(transport)
        await client.initialize()

        tool_calls = [
            {
                "id": "call_001",
                "type": "function",
                "function": {"name": "nonexistent_tool", "arguments": {}},
            }
        ]
        results = await handle_tool_calls(tool_calls, client)
        assert len(results) == 1
        assert "not found" in results[0]["content"].lower()


class TestToolFormatting:
    """Test tool definition formatting for model API."""

    def test_format_tools_for_model(self):
        allowed_tools = [
            {
                "name": "calculator",
                "description": "Evaluate arithmetic",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "expression": {"type": "string", "description": "The expression"},
                    },
                    "required": ["expression"],
                },
            },
            {
                "name": "get_time",
                "description": "Get current time",
                "inputSchema": {"type": "object", "properties": {}, "required": []},
            },
        ]
        result = _format_tools_for_model(allowed_tools)
        assert len(result) == 2
        assert result[0]["type"] == "function"
        assert result[0]["function"]["name"] == "calculator"
        assert result[0]["function"]["parameters"]["type"] == "object"
        assert "expression" in result[0]["function"]["parameters"]["properties"]
        assert result[0]["function"]["parameters"]["required"] == ["expression"]

    def test_format_tools_empty(self):
        result = _format_tools_for_model([])
        assert result == []

    def test_format_tools_missing_schema(self):
        allowed = [{"name": "test", "description": "Test tool"}]
        result = _format_tools_for_model(allowed)
        assert len(result) == 1
        assert result[0]["function"]["parameters"] == {"type": "object", "properties": {}}


class TestToolFiltering:
    """Test tool filtering based on request settings."""

    def test_all_tools_when_web_search_disabled(self):
        allowed = [
            {"name": "calculator", "category": "utility"},
            {"name": "web_search", "category": "web"},
            {"name": "get_time", "category": "utility"},
        ]
        result = _get_allowed_tools_for_request(allowed, web_search_enabled=False)
        names = [t["name"] for t in result]
        assert "calculator" in names
        assert "web_search" not in names
        assert "get_time" in names

    def test_all_tools_when_web_search_enabled(self):
        allowed = [
            {"name": "calculator", "category": "utility"},
            {"name": "web_search", "category": "web"},
            {"name": "get_time", "category": "utility"},
        ]
        result = _get_allowed_tools_for_request(allowed, web_search_enabled=True)
        names = [t["name"] for t in result]
        assert "calculator" in names
        assert "web_search" in names
        assert "get_time" in names

    def test_empty_allowed(self):
        result = _get_allowed_tools_for_request([], web_search_enabled=True)
        assert result == []


class TestMCPClientInMemory:
    """Test MCPClient with InMemoryTransport."""

    @pytest.mark.asyncio
    async def test_initialize(self):
        transport = InMemoryTransport()
        transport.register_handler("tools/list", lambda p: {"tools": []})
        client = MCPClient(transport)
        result = await client.initialize()
        assert result is True

    @pytest.mark.asyncio
    async def test_list_tools(self):
        transport = InMemoryTransport()
        transport.register_handler("tools/list", lambda p: {"tools": [{"name": "test"}]})
        client = MCPClient(transport)
        await client.initialize()
        tools = await client.list_tools()
        assert len(tools) == 1
        assert tools[0]["name"] == "test"

    @pytest.mark.asyncio
    async def test_call_tool(self):
        transport = InMemoryTransport()
        transport.register_handler("tools/call", lambda p: {"content": [{"type": "text", "text": "hello world"}]})
        client = MCPClient(transport)
        await client.initialize()
        result = await client.call_tool("test_tool", {})
        assert "hello" in result


class TestConfigAccess:
    """Test config access functions."""

    def test_allowed_mcp_tools_config(self):
        tools = allowed_mcp_tools_config()
        assert isinstance(tools, list)
        names = [t["name"] for t in tools]
        assert "calculator" in names
        assert "get_time" in names
        assert "web_search" in names

    def test_format_tools_includes_all_allowed(self):
        tools = _format_tools_for_model(allowed_mcp_tools_config())
        names = [t["function"]["name"] for t in tools]
        for name in ["calculator", "get_time", "web_search", "file_read", "get_location"]:
            assert name in names, f"Tool {name} should be in formatted tools"
