"""The codebase must outrank web_search for questions about the user's own code.

Observed failure this pins: with a codebase attached AND web search enabled,
asked "what can you tell me about the main database tables in this project",
the orchestrator called `web_search`, found nothing (the repo is private and
not on the web), and reported it could not help. The codebase tools were in
its tool list the whole time.

Cause: two system-prompt hints competed. The generic web-search hint lists
"documentation" among reasons to search and says "when in doubt, search",
which a question about a project matches; its only guard ("the user's own
files") was a short clause at the end. So when a codebase is present the
web-search hint is swapped for one that scopes web_search to the outside world
and names the codebase as the authority on "this project".
"""
from __future__ import annotations

from app.agent.runtime import (
    CODEBASE_PROJECT_HINT_TEMPLATE,
    WEB_SEARCH_HINT,
    WEB_SEARCH_HINT_WITH_CODEBASE,
    _build_orchestrator_messages,
)
from app.services.memory import MemoryContext

_ALLOWED = [{"name": "web_search", "description": "Search the web", "inputSchema": {}}]


def _msgs(*, web_search: bool, codebase: str | None):
    return _build_orchestrator_messages(
        user_message="What are the main database tables in this project?",
        static_parts=MemoryContext().to_static_messages(),
        dynamic_parts=[],
        evidence_summary="",
        previous_messages=[],
        allowed_tools=_ALLOWED,
        web_search_enabled=web_search,
        codebase_project_name=codebase,
    )


def _system_text(msgs) -> str:
    return "\n".join(m["content"] for m in msgs if m.get("role") == "system")


class TestHintSelection:
    def test_codebase_attached_swaps_in_the_subordinate_web_hint(self):
        text = _system_text(_msgs(web_search=True, codebase="mmcd_metrics"))
        assert "takes precedence" in text
        # The generic hint's strongest pro-search phrases must be gone.
        assert "When in doubt about whether a fact is current, search." not in text

    def test_no_codebase_keeps_the_generic_web_hint(self):
        """Without a codebase there is nothing to defer to — the original
        behaviour must be untouched."""
        text = _system_text(_msgs(web_search=True, codebase=None))
        assert "When in doubt about whether a fact is current, search." in text
        assert "takes precedence" not in text

    def test_web_search_off_emits_neither(self):
        text = _system_text(_msgs(web_search=False, codebase="mmcd_metrics"))
        assert WEB_SEARCH_HINT not in text
        assert WEB_SEARCH_HINT_WITH_CODEBASE not in text


class TestPrecedenceIsStated:
    def test_web_hint_forbids_searching_for_project_questions(self):
        t = WEB_SEARCH_HINT_WITH_CODEBASE.lower()
        assert "never by web_search" in t.replace("\n", " ")
        # Names the concrete phrasings users actually use.
        for phrase in ("this project", "database tables", "the code"):
            assert phrase in t

    def test_codebase_hint_names_schema_questions_explicitly(self):
        """The failing question was about database tables, so that class of
        question must be called out by name rather than left to inference."""
        t = CODEBASE_PROJECT_HINT_TEMPLATE.lower()
        for phrase in ("database tables", "schema", "source of truth"):
            assert phrase in t
        assert "do not use web_search" in t.replace("\n", " ")

    def test_codebase_hint_says_reading_is_the_first_move(self):
        t = CODEBASE_PROJECT_HINT_TEMPLATE.lower()
        assert "codebase_search" in t and "codebase_read_file" in t


class TestPrefixStability:
    def test_hint_bands_are_byte_stable_across_turns(self):
        """The hints sit in the cacheable prefix, so a per-turn difference in
        them would silently destroy prompt caching for every codebase chat.

        Compares only the hint bands. The full system text is deliberately NOT
        byte-stable -- Band C carries a runtime clock that changes every turn --
        and asserting on the whole thing would just be re-testing that clock.
        """
        def hint_bands(msgs):
            return [
                m["content"] for m in msgs
                if m.get("role") == "system"
                and ("takes precedence" in m["content"] or "codebase project named" in m["content"])
            ]

        a = hint_bands(_msgs(web_search=True, codebase="proj"))
        b = hint_bands(_msgs(web_search=True, codebase="proj"))
        assert a and a == b, "hint bands must be identical across turns"
