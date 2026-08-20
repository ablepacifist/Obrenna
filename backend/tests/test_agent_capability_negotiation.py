"""Never offer the model a tool the connected agent cannot perform.

Observed after shipping codebase_find_files: the backend advertised it, the
work laptop was still running an older agent build, and the call came back as

    {"error": true, "message": "Unknown operation: find_files"}

The model does not read that as version skew. It read it as the task being
impossible, stopped trying to locate the document, and spent the rest of the
turn guessing from source files.

The agent now reports its op list at connect. An agent too old to report one is
assumed to support exactly the ops that have always existed.
"""
from __future__ import annotations

from app.ws.codebase_agent_hub import LEGACY_OPS, DeviceConnection


def conn(ops=None) -> DeviceConnection:
    c = DeviceConnection("dev1", websocket=None)
    c.supported_ops = ops
    return c


class TestCapabilityView:
    def test_a_reporting_agent_is_taken_at_its_word(self):
        c = conn({"search", "read_file", "find_files"})
        assert c.supports("find_files") is True
        assert c.supports("run_command") is False, "not reported means not available"

    def test_an_old_agent_keeps_everything_it_always_had(self):
        c = conn(None)
        for op in ("search", "read_file", "run_command", "edit_file", "list_directory"):
            assert c.supports(op) is True, f"{op} predates capability reporting"

    def test_an_old_agent_is_not_offered_the_new_op(self):
        assert conn(None).supports("find_files") is False

    def test_find_files_is_deliberately_absent_from_the_legacy_set(self):
        """If it were listed, an old agent would be offered it again and the
        original failure would return."""
        assert "find_files" not in LEGACY_OPS

    def test_the_legacy_set_covers_the_tools_users_depend_on(self):
        for op in ("search", "read_file", "list_directory", "run_command",
                   "edit_file", "write_file", "delete_file", "move_file"):
            assert op in LEGACY_OPS

    def test_an_agent_reporting_nothing_supports_nothing(self):
        """An explicit empty list is a real answer, not a missing one."""
        assert conn(set()).supports("search") is False


class TestToolAdvertising:
    def test_the_new_tool_is_dropped_for_an_old_agent(self, monkeypatch):
        import app.mcp.codebase_tool_dispatch as ctd

        class Project:
            name = "mmcd_metrics"
            device_id = "dev1"
            write_enabled = True
            id = "p1"

        class Hub:
            def get(self, device_id):
                return conn(None)

        monkeypatch.setattr(ctd, "get_active_codebase_project", lambda cid: Project())
        monkeypatch.setattr(ctd, "get_codebase_agent_hub", lambda: Hub())

        names = [d["name"] for d in ctd.list_enabled_codebase_tool_defs("chat1")]
        assert "codebase_find_files" not in names
        assert "codebase_search" in names, "the old agent's real tools must survive"
        assert "codebase_run_command" in names

    def test_the_new_tool_is_offered_to_an_updated_agent(self, monkeypatch):
        import app.mcp.codebase_tool_dispatch as ctd

        class Project:
            name = "mmcd_metrics"
            device_id = "dev1"
            write_enabled = True
            id = "p1"

        class Hub:
            def get(self, device_id):
                return conn(set(LEGACY_OPS) | {"find_files"})

        monkeypatch.setattr(ctd, "get_active_codebase_project", lambda cid: Project())
        monkeypatch.setattr(ctd, "get_codebase_agent_hub", lambda: Hub())

        assert "codebase_find_files" in [
            d["name"] for d in ctd.list_enabled_codebase_tool_defs("chat1")
        ]

    def test_a_connection_that_cannot_answer_disarms_nothing(self, monkeypatch):
        """In-process and stubbed transports have no capability view; treating
        that as 'supports nothing' would remove every codebase tool."""
        import app.mcp.codebase_tool_dispatch as ctd

        class Project:
            name = "p"
            device_id = "dev1"
            write_enabled = True
            id = "p1"

        class Hub:
            def get(self, device_id):
                return object()  # no .supports

        monkeypatch.setattr(ctd, "get_active_codebase_project", lambda cid: Project())
        monkeypatch.setattr(ctd, "get_codebase_agent_hub", lambda: Hub())

        names = [d["name"] for d in ctd.list_enabled_codebase_tool_defs("chat1")]
        assert "codebase_search" in names
        assert "codebase_run_command" in names
