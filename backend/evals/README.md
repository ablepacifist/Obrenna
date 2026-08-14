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

# Measure the orchestrator path (persona prompt + reasoning-effort ladder)
python -m evals run --target orchestrator --model "qwen3.5:9b"

# Compare against Claude as a reference (needs: pip install anthropic)
python -m evals run --model "qwen3.5:9b" --compare

# Narrow the run while iterating
python -m evals run --model "..." --category math --limit 5
```

Scorecards are written to `evals/results/<label>-<suite>-<timestamp>.json`.
Use `--label` to tag a run (`--label baseline-phase0`) so before/after pairs are
easy to find.

## Two targets — pick the one that matches your question

| `--target` | Path | Use it to measure |
|---|---|---|
| `local` (default) | bare prompt → `chat_completion_sync` | **model selection**, with nothing else varying |
| `orchestrator` | the real `orchestrate_turn` | the **persona prompt**, the **reasoning-effort ladder**, workers, the tool loop |

`local` deliberately skips the orchestrator, which makes it the clean way to
compare two models — no prompt or effort differences confound the result. The
cost is that it is blind to everything the orchestrator adds, so a prompt
change will show up as exactly no movement.

`orchestrator` runs the actual turn pipeline: the persona band (including its
reasoning scaffolding), the ask_user policy, the prompt-JSON tool contract, and
the per-round effort ladder. Memory is stubbed to an **empty** context on
purpose — the persona band comes from `MemoryContext().to_static_messages()`,
so an empty context still exercises the full prompt structure while keeping
runs reproducible. Real retrieval would vary per run with whatever is in your
database, and a scorecard that moves because a stored fact changed is not
measuring the model.

**Expect it to be much slower.** On the seed suite the orchestrator path ran
~80s/case against ~15s/case for `local` — the cost of round-1 effort at `high`
plus the full prompt stack. That difference is a real measurement, not
overhead to be optimised away blindly.

Still **not** exercised by either target: real memory retrieval, knowledge
packs, and codebase tools.

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
