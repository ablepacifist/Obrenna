"""Models the harness can score.

Two kinds, deliberately asymmetric:

* ``LocalTarget`` is the **subject under test** -- the orchestrator this app
  actually runs, reached through ``model_runtime.client.chat_completion_sync``,
  the same function the chat path uses. Going through the project's own client
  (rather than a parallel HTTP call) is the point: a scorecard should reflect
  the real stack, including its endpoint config and timeouts.
* ``ClaudeTarget`` is the **reference** to compare against. It uses the
  Anthropic SDK directly, since that is a different provider from the local
  Ollama-compatible endpoint and does not share its client.

The Claude target is optional. ``anthropic`` is not in requirements.txt, so the
harness must run local-only out of the box -- the import is lazy and the error
message says exactly what to install rather than failing at module import and
taking the whole suite down with it.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from typing import Protocol

from .cases import ReasoningCase

# Wrapped around every case for BOTH targets, so a scorecard compares models
# rather than prompt wording. Asking for the marked final line is what makes
# deterministic grading possible -- see scoring.extract_number, which prefers a
# marked answer precisely because a chain of thought is full of other numbers.
PROMPT_TEMPLATE = (
    "{question}\n\n"
    "Work through this step by step, then give your final answer on the last "
    "line in the form:\n"
    "Answer: <answer>"
)


def build_prompt(case: ReasoningCase) -> str:
    return PROMPT_TEMPLATE.format(question=case.question)


class Target(Protocol):
    """Anything the runner can score."""

    name: str
    model: str

    def generate(self, prompt: str) -> str:
        """Return the model's response text. Raises on failure."""
        ...


@dataclass
class LocalTarget:
    """The local orchestrator, through the app's own model-runtime client."""

    model: str = ""
    name: str = "local"
    timeout: float = 300.0

    def __post_init__(self) -> None:
        from app.model_runtime.config import RuntimeConfig
        from app.services.architecture_config import get_config  # noqa: F401

        # Resolve the endpoint the app itself is configured with, so the
        # scorecard measures the deployed setup rather than a hardcoded one.
        base_url = os.environ.get("OBRENNA_EVAL_BASE_URL", "http://localhost:11434/v1")
        if not self.model:
            self.model = os.environ.get("OBRENNA_EVAL_MODEL", "")
            if not self.model:
                raise ValueError(
                    "No local model specified. Pass --model or set OBRENNA_EVAL_MODEL "
                    "(e.g. 'qwen2.5-coder:14b'). Run `ollama list` to see installed tags."
                )
        self._config = RuntimeConfig(
            provider="openai_compatible",
            base_url=base_url,
            models={"orchestrator": self.model},
        )

    def generate(self, prompt: str) -> str:
        from app.model_runtime.client import chat_completion_sync

        return chat_completion_sync(
            self._config,
            [{"role": "user", "content": prompt}],
            model=self.model,
            timeout=self.timeout,
        )


@dataclass
class ClaudeTarget:
    """Reference target via the Anthropic SDK.

    Notes that are easy to get wrong and would silently skew a scorecard:

    * ``temperature`` / ``top_p`` / ``top_k`` are **removed** on Claude Opus 5
      and return a 400 -- there is no sampling knob to match against the local
      target's. Determinism is not available on either side, which is why the
      suite is scored on aggregate accuracy rather than exact reproduction.
    * A safety classifier can decline a request: HTTP 200 with
      ``stop_reason == "refusal"`` and possibly an empty ``content``. Reading
      ``content[0]`` unconditionally would crash the run, so the refusal is
      checked first and surfaced as a scored error rather than an exception.
    """

    model: str = "claude-opus-5"
    name: str = "claude"
    max_tokens: int = 16000
    effort: str = "high"

    def __post_init__(self) -> None:
        try:
            import anthropic  # noqa: F401
        except ImportError as exc:
            raise RuntimeError(
                "The Claude reference target needs the Anthropic SDK, which this "
                "project does not install by default.\n"
                "  pip install anthropic\n"
                "Credentials: set ANTHROPIC_API_KEY, or run `ant auth login` "
                "(the SDK picks up the stored profile automatically).\n"
                "Omit --compare to run the local target only."
            ) from exc
        import anthropic

        # Zero-arg constructor on purpose: it resolves ANTHROPIC_API_KEY, then
        # ANTHROPIC_AUTH_TOKEN, then an `ant auth login` profile. Passing an
        # explicit key would break the profile path for no benefit.
        self._client = anthropic.Anthropic()

    def generate(self, prompt: str) -> str:
        response = self._client.messages.create(
            model=self.model,
            max_tokens=self.max_tokens,
            thinking={"type": "adaptive"},
            output_config={"effort": self.effort},
            messages=[{"role": "user", "content": prompt}],
        )
        if response.stop_reason == "refusal":
            category = getattr(getattr(response, "stop_details", None), "category", None)
            raise RuntimeError(f"refused by safety classifier (category={category})")
        return "".join(
            block.text for block in response.content if getattr(block, "type", "") == "text"
        )


def build_target(kind: str, *, model: str = "", **kwargs) -> Target:
    if kind == "local":
        return LocalTarget(model=model, **kwargs)
    if kind == "claude":
        return ClaudeTarget(model=model or "claude-opus-5", **kwargs)
    raise ValueError(f"unknown target: {kind!r} (expected 'local' or 'claude')")
