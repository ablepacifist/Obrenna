"""The turn must not end with the agent interviewing the user.

Every assertion here traces to a specific line in a real session where the model
was asked which sites had been dry for two years. In one conversation it:

  * presented SQL naming a column that does not exist, unrun ("did you actually
    run this to see if it worked?"),
  * searched for get_db_connection, was told it exists, and still wrote
    "potentially get_pool()",
  * called codebase_run_command with a real Rscript and then wrote "the tools
    available let me read code files -- not directly query external databases",
  * ended three separate replies with a list of questions for the user, asking
    for connection strings and schema docs that were in the repo.

None of that is a knowledge gap. It is the absence of a rule saying that giving
up and interrogating the user is a failed turn.
"""
from __future__ import annotations

from app.agent.runtime import CODEBASE_PROJECT_HINT_TEMPLATE

HINT = CODEBASE_PROJECT_HINT_TEMPLATE.lower()


class TestDoNotAskWhatYouCanLookUp:
    def test_forbids_asking_for_the_data_source(self):
        assert "what data source" in HINT

    def test_forbids_asking_for_credentials(self):
        assert "credentials" in HINT
        assert "never ask the user for a password" in HINT

    def test_forbids_asking_to_be_pointed_at_the_docs(self):
        assert "point me to the docs" in HINT

    def test_still_allows_asking_about_a_real_decision(self):
        """The rule must not turn into 'never ask anything', or the agent stops
        checking before doing something the user may not want."""
        assert "genuine preference or decision" in HINT


class TestDoNotClaimUntestedLimits:
    def test_the_tool_list_is_named_as_the_source_of_truth(self):
        assert "tool list is the truth" in HINT

    def test_the_exact_phrases_it_used_are_called_out(self):
        for phrase in ("i don't have access to", "i cannot connect to",
                       "the tools only let me read files"):
            assert phrase in HINT, f"the transcript's own wording is not covered: {phrase}"

    def test_it_is_told_it_can_query_databases(self):
        assert "query databases" in HINT


class TestAnEmptySearchIsNotProofOfAbsence:
    def test_retry_strategies_are_spelled_out(self):
        assert "shorter or partial name" in HINT
        assert "regex=false" in HINT

    def test_it_must_report_which_attempts_it_made(self):
        assert "which attempts you made" in HINT


class TestNoHedgingAboutWhatItHasRead:
    def test_the_hedging_words_are_named(self):
        for word in ("may contain", "potentially has", "appears to define"):
            assert word in HINT


class TestRunItBeforeYouShowIt:
    def test_schema_must_be_checked_before_sql_is_written(self):
        assert "before writing sql" in HINT
        assert "describe the columns" in HINT

    def test_inferring_column_names_is_forbidden(self):
        assert "do not infer\ncolumn names" in HINT or "do not infer column names" in HINT.replace("\n", " ")

    def test_it_must_show_what_it_actually_executed(self):
        assert "actually executed" in HINT

    def test_not_running_it_must_be_stated_plainly(self):
        assert "could not run it" in HINT


class TestNarrateAsYouGo:
    def test_it_must_speak_between_tool_calls(self):
        assert "before a tool call" in HINT
        assert "after the result" in HINT

    def test_the_silent_run_of_calls_is_named_as_the_problem(self):
        assert "no words" in HINT


class TestCredentialsAreAlreadyPresent:
    def test_it_is_told_the_env_is_loaded(self):
        assert ".env" in HINT
        assert "already loaded into every command's environment" in HINT

    def test_it_is_told_to_call_the_projects_own_helper(self):
        assert "get_db_connection()" in HINT

    def test_it_is_told_not_to_print_credentials(self):
        assert "never print credentials" in HINT


class TestTheHintStaysUsable:
    def test_it_is_a_single_format_field_template(self):
        """It is formatted with the project name; a stray brace would raise at
        turn assembly rather than at import."""
        rendered = CODEBASE_PROJECT_HINT_TEMPLATE.format(name="mmcd_metrics")
        assert "mmcd_metrics" in rendered

    def test_the_earlier_rules_were_not_displaced(self):
        """These pin behaviour from previous failures; adding rules must not
        quietly drop them."""
        for anchor in ("source of truth", "never claim you created",
                       "do not end your reply by promising"):
            assert anchor in HINT

    def test_it_has_not_grown_past_what_a_local_model_will_follow(self):
        """A prompt long enough to be skimmed is a prompt that stops working."""
        assert len(CODEBASE_PROJECT_HINT_TEMPLATE) < 7000, "too long to hold attention"


# ── the model copying its own past refusals ───────────────────────────────────
# The rules above are system messages. They lose to the conversation's own
# transcript: once a turn has said "I cannot invoke it without actual
# credentials", that sentence sits in context as the model's own prior
# behaviour, and every later turn reproduces it. A user experiences this as "it
# STILL says it can't" long after the capability was fixed.


class TestPastRefusalsAreCorrectedInHistory:
    def _history(self, text: str):
        from app.agent.runtime import _correct_capability_denials
        return _correct_capability_denials([{"role": "assistant", "content": text}])

    def test_the_exact_sentence_from_the_transcript_is_corrected(self):
        out = self._history(
            "Even if get_db_connection() exists in shared/db_helpers.R, I cannot "
            "invoke it without actual credentials from your .env file - which "
            "aren't exposed through this interface."
        )
        assert "was FALSE" in out[0]["content"]
        assert "codebase_run_command" in out[0]["content"]

    def test_the_original_text_is_kept_not_rewritten(self):
        """Editing what the model said would corrupt the transcript; the
        correction is appended so the record stays honest."""
        original = "I do not have access to your database."
        assert self._history(original)[0]["content"].startswith(original)

    def test_a_normal_answer_is_left_alone(self):
        text = "I read shared/db_helpers.R; it defines get_db_connection()."
        assert self._history(text)[0]["content"] == text

    def test_user_messages_are_never_annotated(self):
        from app.agent.runtime import _correct_capability_denials
        msg = {"role": "user", "content": "why can't you access the database?"}
        assert _correct_capability_denials([msg])[0] == msg

    def test_correcting_twice_does_not_stack(self):
        """History is rebuilt every turn, so this runs repeatedly over the same
        message."""
        from app.agent.runtime import _correct_capability_denials
        once = self._history("I cannot access the database.")
        twice = _correct_capability_denials(once)
        assert twice[0]["content"].count("was FALSE") == 1

    def test_non_string_content_does_not_raise(self):
        from app.agent.runtime import _correct_capability_denials
        msg = {"role": "assistant", "content": None}
        assert _correct_capability_denials([msg])[0] == msg

    def test_it_only_applies_when_a_codebase_is_attached(self):
        """With no project there are no codebase tools, so 'I cannot read your
        files' is true and must not be contradicted."""
        from app.agent.runtime import _build_orchestrator_messages
        history = [{"role": "assistant", "content": "I cannot access your files."}]
        without = _build_orchestrator_messages(
            "hi", [], [], "", history, tool_call_mode="openai_native",
            allowed_tools=[], web_search_enabled=False,
            codebase_project_name=None, agent_mode="auto",
        )
        assert not any("was FALSE" in m["content"] for m in without)

        with_project = _build_orchestrator_messages(
            "hi", [], [], "", history, tool_call_mode="openai_native",
            allowed_tools=[], web_search_enabled=False,
            codebase_project_name="mmcd_metrics", agent_mode="auto",
        )
        assert any("was FALSE" in m["content"] for m in with_project)


class TestNoFabricatedLooking:
    def test_claiming_to_have_searched_is_forbidden(self):
        assert "never say you searched" in HINT

    def test_a_failed_read_is_not_proof_of_absence(self):
        assert "failed file read is not proof" in HINT


class TestFindingAFileByName:
    """codebase_search looks INSIDE files. Asked where the schema document was,
    the model searched contents for 'SCHEMA|TABLES|database.*doc', found
    nothing, and reported the documentation as missing."""

    def test_the_filename_tool_is_pointed_at(self):
        assert "codebase_find_files" in HINT

    def test_the_distinction_is_made_explicit(self):
        assert "searches filenames" in HINT
        assert "searches inside files" in HINT


class TestNoRepeatedCalls:
    def test_repeating_a_call_is_named_as_a_failure(self):
        assert "repeating a call you already made" in HINT
