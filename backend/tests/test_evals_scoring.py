"""Tests for eval answer-extraction and grading.

The extractor is the harness's single point of failure: if it misreads answers,
every scorecard is noise and every "this improved reasoning" conclusion drawn
from one is wrong. The cases below are the response shapes models actually
produce -- chain-of-thought with many intermediate numbers, \\boxed{}, restated
questions, markdown bold -- not just the happy path.
"""
from __future__ import annotations

import pytest

from evals.cases import ReasoningCase, load_cases, summarize
from evals.scoring import extract_choice, extract_number, grade


class TestExtractNumber:
    def test_plain_marked_answer(self):
        assert extract_number("The answer is 42") == "42"

    def test_answer_colon(self):
        assert extract_number("Answer: 13.5") == "13.5"

    def test_boxed_wins_over_everything(self):
        text = "First I get 10, then 20. Answer: 30. \\boxed{40}"
        assert extract_number(text) == "40"

    def test_ignores_intermediate_chain_of_thought_numbers(self):
        """The whole reason marked answers are preferred over 'last number'."""
        text = (
            "6 pens at $3 each is 18 dollars.\n"
            "A 25% discount removes 4.5.\n"
            "Answer: 13.5"
        )
        assert extract_number(text) == "13.5"

    def test_last_marker_wins_when_question_is_restated(self):
        """Models often echo 'to find the answer' before actually solving."""
        text = "To find the answer, note 5 items. Working... The answer is 25."
        assert extract_number(text) == "25"

    def test_strips_commas_and_currency(self):
        assert extract_number("Answer: $12,800") == "12800"

    def test_normalises_integral_floats(self):
        assert extract_number("Answer: 90.0") == "90"

    def test_negative(self):
        assert extract_number("Answer: -17") == "-17"

    def test_markdown_bold_marker(self):
        assert extract_number("**Answer:** 72") == "72"

    def test_trailing_period_is_not_a_decimal_point(self):
        assert extract_number("Answer: 55.") == "55"

    def test_falls_back_to_last_number_when_unmarked(self):
        assert extract_number("So we end up with 96 dollars") == "96"

    def test_empty_and_no_number(self):
        assert extract_number("") == ""
        assert extract_number("I cannot determine this.") == ""


class TestExtractChoice:
    def test_answer_letter(self):
        assert extract_choice("Answer: C") == "C"

    def test_parenthesised(self):
        assert extract_choice("The answer is (B)") == "B"

    def test_lowercase_normalised(self):
        assert extract_choice("answer: d") == "D"

    def test_not_confused_by_letters_inside_words(self):
        """'A' in 'All' must not be read as choice A."""
        assert extract_choice("All roses are flowers. Answer: C") == "C"

    def test_boxed(self):
        assert extract_choice("\\boxed{B}") == "B"

    def test_no_choice_present(self):
        assert extract_choice("I'm not sure about this one.") == ""


class TestGrade:
    def test_numeric_correct_and_incorrect(self):
        assert grade("Answer: 42", grader="numeric", expected="42") == (True, "42")
        assert grade("Answer: 41", grader="numeric", expected="42") == (False, "41")

    def test_numeric_equivalent_forms_match(self):
        correct, _ = grade("Answer: 13.50", grader="numeric", expected="13.5")
        assert correct

    def test_mcq(self):
        assert grade("Answer: B", grader="mcq", expected="B")[0] is True
        assert grade("Answer: A", grader="mcq", expected="B")[0] is False

    def test_empty_response_is_never_correct(self):
        """A dead endpoint must not score as a pass."""
        assert grade("", grader="numeric", expected="42")[0] is False
        assert grade("", grader="mcq", expected="B")[0] is False

    def test_contains_reports_which_terms_are_missing(self):
        correct, detail = grade(
            "I used a hammer.", grader="contains", expected="",
            required_terms=["hammer", "nail"],
        )
        assert correct is False
        assert "nail" in detail

    def test_unknown_grader_raises(self):
        with pytest.raises(ValueError):
            grade("x", grader="vibes", expected="y")


class TestSuiteData:
    def test_bundled_suite_is_well_formed(self):
        """Every shipped case must be gradeable — a malformed answer would
        silently score 0% forever and look like a model regression."""
        cases = load_cases("reasoning_seed")
        assert len(cases) >= 20

        ids = [c.id for c in cases]
        assert len(ids) == len(set(ids)), "case ids must be unique"

        for case in cases:
            assert case.question.strip(), f"{case.id}: empty question"
            assert case.grader in {"numeric", "mcq", "contains"}, case.id
            if case.grader == "numeric":
                # The expected answer must survive the same normalisation the
                # model's answer goes through, or nothing can ever match it.
                assert extract_number(f"Answer: {case.answer}") != "", case.id
            if case.grader == "mcq":
                assert case.answer in {"A", "B", "C", "D"}, case.id
                assert case.choices, f"{case.id}: mcq needs choices"

    def test_a_perfect_run_scores_100_percent(self):
        """End-to-end sanity: feed each case its own answer and expect 100%.
        Catches a systemic extractor/answer-format mismatch in one assertion."""
        cases = load_cases("reasoning_seed")
        for case in cases:
            correct, extracted = grade(
                f"Reasoning here.\nAnswer: {case.answer}",
                grader=case.grader,
                expected=case.answer,
                required_terms=case.required_terms,
            )
            assert correct, f"{case.id}: expected {case.answer!r}, extracted {extracted!r}"


class TestSummarize:
    def test_aggregates_by_category(self):
        from evals.cases import CaseResult

        results = [
            CaseResult("m1", "math", True, "1", "1", 100.0),
            CaseResult("m2", "math", False, "2", "3", 200.0),
            CaseResult("l1", "logic", True, "A", "A", 300.0),
        ]
        out = summarize("local", "test-model", results)
        assert out.cases == 3
        assert out.correct == 2
        assert out.accuracy == pytest.approx(2 / 3)
        assert out.by_category["math"] == pytest.approx(0.5)
        assert out.by_category["logic"] == pytest.approx(1.0)

    def test_errors_counted_and_never_correct(self):
        from evals.cases import CaseResult

        out = summarize("local", "m", [
            CaseResult("a", "math", False, "", "1", 10.0, error="Timeout"),
        ])
        assert out.errors == 1
        assert out.accuracy == 0.0

    def test_empty_results_do_not_crash(self):
        out = summarize("local", "m", [])
        assert out.cases == 0 and out.accuracy == 0.0


# ── behavioural grading ───────────────────────────────────────────────────────
# Some failures are things the model SAYS, not answers it gets wrong: claiming
# it cannot reach a database it can reach, hedging about a file it has read,
# ending a turn by asking the user for a fact that is in the repo. Those cases
# have no answer to match — only wrong things to not say.


def test_a_forbidden_phrase_fails_the_case():
    ok, extracted = grade(
        "I do not have access to your live database.",
        grader="contains", expected="",
        forbidden_terms=["i do not have access"],
    )
    assert ok is False
    assert "said:" in extracted, "the report must name what it said, for triage"


def test_a_clean_response_passes_on_forbidden_terms_alone():
    ok, _ = grade(
        "Yes — I can run an Rscript against it with codebase_run_command.",
        grader="contains", expected="",
        forbidden_terms=["i do not have access"],
    )
    assert ok is True


def test_forbidden_matching_is_case_insensitive():
    ok, _ = grade("I CANNOT ACCESS that.", grader="contains", expected="",
                  forbidden_terms=["i cannot access"])
    assert ok is False


def test_required_and_forbidden_terms_combine():
    args = dict(grader="contains", expected="",
                required_terms=["get_db_connection"], forbidden_terms=["potentially"])
    assert grade("It defines get_db_connection.", **args)[0] is True
    # Right content, wrong hedge — still a failure.
    assert grade("It potentially defines get_db_connection.", **args)[0] is False
    # No hedge, but never answered.
    assert grade("The file exists.", **args)[0] is False


def test_a_case_with_no_terms_at_all_is_not_a_free_pass():
    assert grade("anything", grader="contains", expected="")[0] is False


def test_forbidden_terms_are_optional():
    """Existing required-only cases must grade exactly as before."""
    assert grade("the capital is Paris", grader="contains", expected="",
                 required_terms=["paris"])[0] is True
