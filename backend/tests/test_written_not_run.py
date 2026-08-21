"""Writing a command is not running it.

Both of these are verbatim from one conversation, after the model had already
successfully connected to the live database. It typed the next command into its
reply, explained what the output would show, and stopped — twice, with the user
having to say "you didnt run any command" in between.

The existing preamble guard could not catch them: it bails on anything over 320
characters, and this failure is verbose by construction — a full command plus a
paragraph about what it "will" show.
"""
from __future__ import annotations

from app.agent.runtime import _looks_like_unfinished_narration as unfinished

FIRST_FAILURE = """Running Database Verification with Rscript

You're right — I should actually run the verification commands now that you've \
added it to the path. Let me do that:

Rscript -e "source('shared/db_helpers.R'); con <- get_db_connection(); dbListTables(con, 'public')"

This will list all public tables in the database and confirm our connection is \
working properly."""

SECOND_FAILURE = """Database Connection Verified

The connection is working perfectly! I can see all 501 public tables listed, \
including key ones like loc_breeding_site_cards_sjsreast2 and gis_sectcode.

Next Steps to Build the Correct SQL

I need to examine the actual column names in the relevant tables. Let me query \
a few key ones:

Rscript -e "source('shared/db_helpers.R'); con <- get_db_connection();
dbGetQuery(con, 'SELECT column_name, data_type FROM information_schema.columns \
WHERE table_name = ''loc_breeding_site_cards_sjsreast2'' ORDER BY ordinal_position')"

This will show me the exact columns available for priority (GREEN), fosarea \
values, and date fields."""


class TestTheObservedFailures:
    def test_the_first_one_is_caught(self):
        assert unfinished(FIRST_FAILURE) is True

    def test_the_second_one_is_caught(self):
        assert unfinished(SECOND_FAILURE) is True

    def test_they_are_both_past_the_old_length_gate(self):
        """Proves the new signal is doing the work, not the old heuristics."""
        assert len(FIRST_FAILURE) > 320
        assert len(SECOND_FAILURE) > 320


class TestOtherRunnersAreCaught:
    def test_python(self):
        assert unfinished("Let me check the schema:\n\npython -c \"import db; print(db.tables())\"\n\n"
                          "This will print every table so I can pick the right one.") is True

    def test_npm(self):
        assert unfinished("I'll verify the build now:\n\nnpm run build\n\n"
                          "That will tell us whether the change compiles.") is True

    def test_a_fenced_block(self):
        assert unfinished("Next I will run:\n\n```bash\npytest tests/ -q\n```\n\n"
                          "This will confirm nothing regressed.") is True

    def test_a_shell_prompt_prefix(self):
        assert unfinished("Let me try:\n\n$ psql -c \"\\dt\"\n\nThis will list the tables.") is True


class TestRealAnswersAreNotNudged:
    def test_an_answer_that_shows_the_user_a_command_is_left_alone(self):
        """No future-intent framing: this is the finished answer, not a promise."""
        text = ("To reproduce this yourself, run:\n\n```bash\npytest tests/ -q\n```\n\n"
                "All 690 tests passed on my last run, and the fix is in "
                "backend/app/agent/runtime.py.")
        assert unfinished(text) is False

    def test_a_report_of_a_command_already_run_is_left_alone(self):
        text = ("I ran `Rscript -e \"dbListTables(con)\"` and it returned 501 tables, "
                "including loc_breeding_site_cards_sjsreast2 and gis_sectcode. "
                "The connection works.")
        assert unfinished(text) is False

    def test_prose_mentioning_a_tool_name_is_not_a_command(self):
        """'python' in a sentence must not look like an invocation."""
        text = ("The project is written in python and R. This will vary by app, but "
                "most of them read from the same database. " + "x" * 400)
        assert unfinished(text) is False

    def test_a_long_substantive_answer_is_still_safe(self):
        assert unfinished("The schema stores wetness in status_udw. " * 30) is False

    def test_empty_output_is_not_claimed(self):
        assert unfinished("") is False


class TestTheOldSignalsStillWork:
    def test_a_trailing_colon_still_counts(self):
        assert unfinished("Let me check that directory:") is True

    def test_a_short_intention_line_still_counts(self):
        assert unfinished("I'll read the file now") is True

    def test_a_plain_short_answer_is_still_fine(self):
        assert unfinished("The function is defined in shared/db_helpers.R.") is False
