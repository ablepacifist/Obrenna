# Reasoning eval harness

Produces a diffable scorecard so "this improved reasoning" is a measurable
claim rather than an impression. The runtime is instrumented for latency only
(`TurnTelemetry`); nothing else in this repo measures whether an answer is
*correct*.

## Usage

```bash
cd backend

# List bundled suites
python -m evals suites

# Score the local model
python -m evals run --model "qwen2.5-coder:14b"

# Compare against Claude as a reference (needs: pip install anthropic)
python -m evals run --model "qwen3.5:9b" --compare

# Narrow the run while iterating
python -m evals run --model "..." --category math --limit 5
```

Scorecards are written to `evals/results/<label>-<suite>-<timestamp>.json`.
Use `--label` to tag a run (`--label baseline-phase0`) so before/after pairs are
easy to find.

## What it measures — and what it does NOT

**It measures raw model capability.** `LocalTarget` calls the model directly
through `model_runtime.client.chat_completion_sync` with a single prompt. It
deliberately does **not** go through `orchestrate_turn`, so none of the
following are exercised:

- the persona / system prompt bands (`ORCHESTRATOR_STATIC_SYSTEM_PROMPT`)
- memory retrieval and knowledge packs
- the reasoning-effort ladder (`_reasoning_effort_for_round`)
- tools, the write gate, `ask_user`

**Consequence:** this harness cleanly attributes a **model-selection** change
(swapping which model is the orchestrator) because nothing else varies. It will
**not** detect a change to the persona prompt or to reasoning-effort defaults —
those only take effect on the `orchestrate_turn` path. Measuring those needs an
orchestrator-path target, which does not exist yet.

That split is deliberate: isolating the model keeps the largest single lever
free of confounds. But do not read a flat scorecard as "the prompt change did
nothing" — read it as "this harness cannot see prompt changes."

## Suites

`suites/reasoning_seed.jsonl` ships with the harness so a scorecard can be
produced offline, with no dataset downloads. Categories: `math` (multi-step
arithmetic), `logic` (formal deduction), `semantic` (reference resolution and
entailment), `multihop` (fact chaining), `commonsense` (physical reasoning).

Public benchmarks load from an external JSONL of the same shape:

```bash
python -m evals run --cases /path/to/gsm8k.jsonl --model "..."
```

Case schema (one JSON object per line):

```json
{"id": "math-01", "category": "math", "grader": "numeric",
 "answer": "13.5", "question": "..."}
```

`grader` is `numeric` (final number must match), `mcq` (final choice letter), or
`contains` (every `required_terms` entry must appear).

## Grading

Deterministic, never model-judged — a score change must mean the model changed,
not that a judge drifted. `scoring.py` prefers an explicitly marked final answer
(`Answer: 42`, `\boxed{42}`) over positional heuristics, because a
chain-of-thought response is full of intermediate numbers and the last one is
not reliably the result. Every case records what was `extracted` alongside
whether it was `correct`, so a failure can be triaged as "model got it wrong"
vs "extractor missed it" without re-running.

Extractor behaviour is pinned by `tests/test_evals_scoring.py`, including an
end-to-end check that feeding every case its own answer scores 100% — that one
assertion catches a systemic answer-format mismatch.
