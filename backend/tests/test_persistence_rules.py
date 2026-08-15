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
        assert "already" in HINT and "loaded into the environment" in HINT

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
