"""Core memory service: budgets, retrieval, context assembly, turn recording, summary folding, fact reconciliation."""
from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy.orm import Session

from ..model_runtime.client import chat_completion_sync
from ..model_runtime.config import RuntimeConfig
from ..services.embeddings import embed_text
from ..services.memory_config import (
    CONTEXT_TIERS,
    DEFAULT_CONTEXT_TIER,
    EMBEDDING_DIM,
    MAX_FACTS_PER_TURN,
    TIGHT_ARCHIVE_TOP_K,
    TIGHT_FACT_TOP_K,
    get_default_top_k,
    get_extraction_limit,
    get_memory_config,
    get_similarity_threshold,
)
from ..services.vector_store import (
    delete_fact_vector,
    delete_turn_vector,
    insert_fact_vector,
    insert_turn_vector,
    search_facts,
    search_turns,
)

logger = logging.getLogger(__name__)

# ── Prompts ───────────────────────────────────────────────────────────────────

FOLD_SUMMARY_PROMPT = (
    "You are folding one conversation turn into an existing rolling summary.\n"
    "Do NOT rewrite or re-summarize the existing summary. "
    "Only add information from the new turn that is not already covered.\n\n"
    "Existing rolling summary:\n{{summary}}\n\n"
    "New turn to fold in:\n"
    "User: {{user_text}}\n"
    "Assistant: {{assistant_text}}\n\n"
    "Output only the updated summary (append new info, keep it concise):"
)

FACT_EXTRACTION_PROMPT = (
    "Extract up to {{max_facts}} coarse, self-contained narrative facts from this conversation turn.\n"
    "Facts should be about the user's project, preferences, decisions, or domain context.\n"
    "Output a JSON list of strings, or an empty list if nothing extractable.\n"
    "Do NOT include greetings, clarifications, or meta-comments.\n\n"
    "User: {{user_text}}\n"
    "Assistant: {{assistant_text}}\n\n"
    "Facts (JSON array):"
)

RECONCILE_PROMPT = (
    "Reconcile a newly extracted fact against an existing stored fact.\n"
    "Respond with one operation: ADD, UPDATE, DELETE, or NOOP.\n"
    "If UPDATE, also provide the existing fact id to update.\n"
    "Never UPDATE or DELETE a user-locked fact.\n\n"
    "Existing fact (id={{existing_id}}, locked={{is_locked}}, text={{existing_text}}):\n"
    "New candidate (text={{candidate_text}}):\n\n"
    "Output JSON:\n"
    '{"op": "ADD"|"UPDATE"|"DELETE"|"NOOP", "target_id": null or "existing_id"}'
)

# ── Budget ────────────────────────────────────────────────────────────────────


def pick_memory_budget(ctx_max: int | None) -> int:
    """Return the memory archive retrieval budget (in tokens) for the given context size."""
    if ctx_max is None:
        ctx_max = DEFAULT_CONTEXT_TIER
    # Find the largest tier <= ctx_max by iterating in reverse
    tiers = sorted(CONTEXT_TIERS.keys(), reverse=True)
    for t in tiers:
        if ctx_max >= t:
            return CONTEXT_TIERS[t]
    # Below smallest tier, use smallest budget
    return CONTEXT_TIERS[min(CONTEXT_TIERS.keys())]


# ── Context assembly ──────────────────────────────────────────────────────────


class MemoryContext:
    """Structured context payload returned by assemble_context."""

    def __init__(
        self,
        recency: list[dict] | None = None,
        rolling_summary: str = "",
        facts: list[dict] | None = None,
        archive_turns: list[dict] | None = None,
    ):
        self.recency = recency or []
        self.rolling_summary = rolling_summary
        self.facts = facts or []
        self.archive_turns = archive_turns or []

    def to_messages(self) -> list[dict]:
        """Convert to a list of LLM system/user messages for the orchestrator."""
        messages: list[dict] = []
        parts: list[str] = []

        # 1. Rolling summary always
        if self.rolling_summary:
            parts.append(f"**Context Summary (from previous turns):**\n{self.rolling_summary}")

        # 2. Account/local facts
        if self.facts:
            fact_lines = "\n".join(f"- {f['text']}" for f in self.facts)
            parts.append(f"**Your stored memories:**\n{fact_lines}")

        # 3. Retrieved archive turns (only when context is tight, trimmed)
        if self.archive_turns:
            turn_lines = "\n".join(
                f"[Turn {t.get('turn_index', '')}] User: {t['user_text']}\n"
                f"  Assistant: {t['assistant_text']}"
                for t in self.archive_turns
            )
            parts.append(f"**Relevant past conversation:**\n{turn_lines}")

        # Only include markdown hint when there's actual context content
        if parts:
            parts.append(
                "You may use Markdown formatting in your responses (headers, bold, lists, "
                "code blocks, tables) when it improves readability. Plain prose is fine when "
                "markdown would add no value."
            )

        if parts:
            messages.append({"role": "system", "content": "\n\n".join(parts)})

        return messages


def assemble_context(
    db: Session,
    chat: Any,
    user_message: str,
    *,
    recent_count: int = 6,
) -> MemoryContext:
    """Build memory context for a chat turn.

    Precedence: recency buffer → rolling summary → facts → archive turns.
    """
    from ..models import ChatMessage, ChatTurn  # noqa: PLC0414

    # Recency buffer: last N assistant messages before this turn
    recency: list[dict] = []
    all_msgs = (
        db.query(ChatMessage)
        .filter_by(chat_id=chat.id)
        .filter(ChatMessage.role == "assistant")
        .order_by(ChatMessage.created_at.desc())
        .limit(recent_count)
        .all()
    )
    for m in reversed(all_msgs):
        recency.append({"role": "assistant", "text": m.text})

    # Rolling summary
    rolling_summary = getattr(chat, "rolling_summary", "") or ""

    # Memory facts
    facts = search_facts(db, user_message, top_k=get_default_top_k())
    facts_out = [{"id": f[0], "text": f[2]} for f in facts]

    # Archived turns (determine top-k based on budget)
    budget = getattr(chat, "managed_ctx", None) or getattr(chat, "_managed_ctx", None)
    ctx_max = None
    if budget:
        ctx_max = budget
    managed_plan = getattr(chat, "managed_plan", None) or {}
    if isinstance(managed_plan, dict) and managed_plan.get("ctx"):
        ctx_max = managed_plan["ctx"]
    if not ctx_max:
        # Try to get from AppSettings
        try:
            from ..models import AppSettings  # noqa: PLC0414
            app_settings = db.get(AppSettings, 1)
            if app_settings and isinstance(app_settings.managed_plan, dict):
                ctx_max = app_settings.managed_plan.get("ctx")
        except Exception:
            pass

    budget_tokens = pick_memory_budget(ctx_max) if ctx_max else 4096
    archive_top_k = TIGHT_ARCHIVE_TOP_K if budget_tokens < 4096 else TIGHT_ARCHIVE_TOP_K
    facts_top_k = TIGHT_FACT_TOP_K if budget_tokens < 4096 else FACT_TOP_K

    archive_scores = search_turns(db, chat.id, user_message, top_k=archive_top_k * 2)
    archive_out: list[dict] = []
    for sim, turn_id in archive_scores:
        turn = db.query(ChatTurn).filter_by(id=turn_id).first()
        if turn:
            archive_out.append({
                "id": turn.id,
                "turn_index": turn.turn_index,
                "user_text": turn.user_text[:200],
                "assistant_text": turn.assistant_text[:200],
            })

    return MemoryContext(
        recency=recency,
        rolling_summary=rolling_summary,
        facts=facts_out,
        archive_turns=archive_out,
    )


def build_model_messages(
    user_message: str,
    context: MemoryContext,
) -> list[dict]:
    """Convert memory context into a system/user message sequence for the orchestrator."""
    system_messages = context.to_messages()
    if system_messages:
        return system_messages + [{"role": "user", "content": user_message}]
    return [{"role": "user", "content": user_message}]


# ── Turn recording ────────────────────────────────────────────────────────────


def record_turn_after_response(
    db: Session,
    chat: Any,
    user_msg: Any,
    assistant_msg: Any,
) -> Optional[str]:
    """Create a ChatTurn record and insert its embedding vector.

    Returns the turn id, or None if embedding failed.
    """
    from ..models import ChatTurn  # noqa: PLC0414

    try:
        # Determine turn_index
        last_turn = (
            db.query(ChatTurn)
            .filter_by(chat_id=chat.id)
            .order_by(ChatTurn.turn_index.desc())
            .first()
        )
        next_index = (last_turn.turn_index + 1) if last_turn else 0

        turn = ChatTurn(
            id=uuid.uuid4().hex,
            chat_id=chat.id,
            turn_index=next_index,
            user_message_id=user_msg.id,
            assistant_message_id=assistant_msg.id,
            user_text=user_msg.text,
            assistant_text=assistant_msg.text,
            created_at=assistant_msg.created_at,
        )
        db.add(turn)
        db.commit()
        db.refresh(turn)

        # Insert vector
        content = f"{user_msg.text} {assistant_msg.text}"
        insert_turn_vector(db, turn.id, content)

        # Update rolling summary if needed (fold aged-out turn)
        _maybe_fold_summary(db, chat, turn)

        return turn.id
    except Exception as exc:
        db.rollback()
        logger.warning("Failed to record turn: %s", exc)
        return None


# ── Summary folding ──────────────────────────────────────────────────────────


def _maybe_fold_summary(
    db: Session,
    chat: Any,
    new_turn: Any,
) -> bool:
    """Fold the oldest newly aged-out turn into the rolling summary if needed."""
    from ..models import AppSettings, ModelEndpoint  # noqa: PLC0414

    summarized_upto = getattr(chat, "summarized_upto_turn_index", -1)
    turn_index = new_turn.turn_index

    # Only fold when a turn has aged out beyond the summarized range
    # A turn ages out when it's no longer in the recency buffer
    budget = pick_memory_budget(getattr(chat, "managed_ctx", None))
    # Rough approximation: fold every 4 turns beyond summarized_upto
    if summarized_upto < 0 or (turn_index - summarized_upto) < 4:
        return False

    # Get the turn to fold (the one just past summarized_upto)
    turn_to_fold = (
        db.query(ChatTurn)
        .filter_by(chat_id=chat.id, turn_index=summarized_upto + 1)
        .first()
    )
    if not turn_to_fold:
        return False

    existing_summary = getattr(chat, "rolling_summary", "") or ""

    # Use the utility/summarizer model to fold
    ep = db.get(ModelEndpoint, 1)
    if not ep or not ep.base_url:
        return False

    cfg = RuntimeConfig(
        provider=ep.provider,
        base_url=ep.base_url,
        api_key=ep.api_key or "",
        models=ep.models or {},
    )
    chosen_model = cfg.model_for("summarizer") or cfg.model_for("utility") or ""

    prompt = FOLD_SUMMARY_PROMPT.format(
        summary=existing_summary[:1000],
        user_text=turn_to_fold.user_text[:500],
        assistant_text=turn_to_fold.assistant_text[:500],
    )

    try:
        new_summary = chat_completion_sync(
            cfg,
            [{"role": "user", "content": prompt}],
            model=chosen_model,
            role="summarizer",
            temperature=0.1,
        )
        chat.rolling_summary = new_summary.strip()
        chat.summarized_upto_turn_index = turn_to_fold.turn_index
        db.commit()
        return True
    except Exception as exc:
        db.rollback()
        logger.warning("Summary fold failed: %s", exc)
        return False


# ── Fact extraction & reconciliation ──────────────────────────────────────────


def _extract_facts(
    db: Session,
    user_text: str,
    assistant_text: str,
) -> list[str]:
    """Ask the model to extract narrative facts from a conversation turn."""
    from ..models import ModelEndpoint  # noqa: PLC0414

    ep = db.get(ModelEndpoint, 1)
    if not ep or not ep.base_url:
        return []

    cfg = RuntimeConfig(
        provider=ep.provider,
        base_url=ep.base_url,
        api_key=ep.api_key or "",
        models=ep.models or {},
    )
    chosen = cfg.model_for("utility") or cfg.model_for("summarizer") or ""

    prompt = FACT_EXTRACTION_PROMPT.format(
        max_facts=get_extraction_limit(),
        user_text=user_text[:800],
        assistant_text=assistant_text[:800],
    )

    try:
        response = chat_completion_sync(
            cfg,
            [{"role": "user", "content": prompt}],
            model=chosen,
            role="utility",
            temperature=0.1,
            timeout=60.0,
        )
        # Parse JSON from response
        text = response.strip()
        # Try to find JSON array
        start = text.find("[")
        end = text.rfind("]") + 1
        if start >= 0 and end > start:
            text = text[start:end]
        facts = json.loads(text)
        if isinstance(facts, list):
            return [f for f in facts if isinstance(f, str) and len(f) > 5]
    except Exception as exc:
        logger.warning("Fact extraction failed: %s", exc)

    return []


def _reconcile_fact(
    db: Session,
    candidate: str,
    existing: Any,
) -> tuple[str, Optional[str]]:
    """Decide whether to ADD, UPDATE, DELETE, or NOOP a candidate fact.

    Returns (operation, target_id).
    """
    from ..models import ModelEndpoint  # noqa: PLC0414

    ep = db.get(ModelEndpoint, 1)
    if not ep or not ep.base_url:
        return ("NOOP", None)

    cfg = RuntimeConfig(
        provider=ep.provider,
        base_url=ep.base_url,
        api_key=ep.api_key or "",
        models=ep.models or {},
    )
    chosen = cfg.model_for("utility") or ""

    prompt = RECONCILE_PROMPT.format(
        existing_id=existing.id,
        is_locked=existing.user_locked,
        existing_text=existing.fact_text[:500],
        candidate_text=candidate[:500],
    )

    try:
        response = chat_completion_sync(
            cfg,
            [{"role": "user", "content": prompt}],
            model=chosen,
            role="utility",
            temperature=0.1,
            timeout=60.0,
        )
        text = response.strip()
        start = text.find("{")
        end = text.rfind("}") + 1
        if start >= 0 and end > start:
            text = text[start:end]
        result = json.loads(text)
        op = result.get("op", "NOOP")
        target_id = result.get("target_id")

        # Never update/delete user-locked facts
        if existing.user_locked and op in ("UPDATE", "DELETE"):
            return ("NOOP", None)
        return (op, target_id)
    except Exception as exc:
        logger.warning("Fact reconcile failed: %s", exc)
        return ("NOOP", None)


def extract_and_reconcile_facts(
    db: Session,
    user_msg: Any,
    assistant_msg: Any,
    source_chat_id: str | None = None,
) -> list[dict]:
    """Extract candidate facts and reconcile against existing facts.

    Returns list of events: [{"type": "ADD"|"UPDATE", "fact_id": str, "text": str}].
    Runs in background and does not affect chat persistence.
    """
    from ..models import MemoryFact  # noqa: PLC0414

    try:
        candidates = _extract_facts(db, user_msg.text, assistant_msg.text)
        if not candidates:
            return []

        events: list[dict] = []
        existing_facts = (
            db.query(MemoryFact)
            .filter_by(account_id=MemoryFact.ACCOUNT_ID)
            .filter(MemoryFact.deleted_at.is_(None))
            .all()
        )

        for candidate in candidates:
            # Check similarity against existing facts
            best_match = None
            best_score = 0
            candidate_vec = embed_text(candidate)
            if candidate_vec:
                for fact in existing_facts:
                    fact_vec = embed_text(fact.fact_text)
                    if fact_vec:
                        from ..services.vector_store import _cosine  # noqa: PLC0414
                        sim = _cosine(candidate_vec, fact_vec)
                        if sim > best_score:
                            best_score = sim
                            best_match = fact

            if best_match and best_score >= get_similarity_threshold():
                op, _ = _reconcile_fact(db, candidate, best_match)
                if op == "UPDATE":
                    best_match.fact_text = candidate
                    best_match.updated_at = datetime.now(timezone.utc)
                    insert_fact_vector(db, best_match.id, candidate)
                    events.append({"type": "UPDATE", "fact_id": best_match.id, "text": candidate})
                elif op == "ADD":
                    # Treat as new fact
                    _add_fact(db, candidate, source_chat_id, source="auto")
                    events.append({"type": "ADD", "text": candidate})
            else:
                # No close match — add as new fact
                _add_fact(db, candidate, source_chat_id, source="auto")
                events.append({"type": "ADD", "text": candidate})

        if events:
            db.commit()
        return events
    except Exception as exc:
        db.rollback()
        logger.warning("Fact extraction/reconciliation failed: %s", exc)
        return []


def _add_fact(
    db: Session,
    text: str,
    source_chat_id: str | None,
    *,
    source: str = "user",
) -> Optional[Any]:
    """Insert a new memory fact and its vector.

    Args:
        db: SQLAlchemy session.
        text: The fact text.
        source_chat_id: Optional chat ID that originated this fact.
        source: "user" for user-created facts, "auto" for auto-extracted facts.
            Determines initial user_locked state.
    """
    from ..models import MemoryFact  # noqa: PLC0414

    cfg = get_memory_config()
    user_locked = cfg.user_facts.created_by_user_default_locked if source == "user" else False

    fact = MemoryFact(
        id=uuid.uuid4().hex,
        fact_text=text,
        source_chat_id=source_chat_id,
        user_locked=user_locked,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    db.add(fact)
    db.commit()
    db.refresh(fact)
    insert_fact_vector(db, fact.id, text)
    return fact


def get_active_facts(db: Session) -> list[Any]:
    """Return all active (non-deleted) memory facts ordered by updated_at desc."""
    from ..models import MemoryFact  # noqa: PLC0414

    return (
        db.query(MemoryFact)
        .filter_by(account_id=MemoryFact.ACCOUNT_ID)
        .filter(MemoryFact.deleted_at.is_(None))
        .order_by(MemoryFact.updated_at.desc())
        .all()
    )


def update_fact(
    db: Session,
    fact_id: str,
    new_text: str,
    *,
    actor: str = "user",
) -> Optional[Any]:
    """Update a fact's text and recompute embedding.

    Args:
        db: SQLAlchemy session.
        fact_id: The fact to update.
        new_text: The new fact text.
        actor: "user" for user-initiated updates. Auto-memory actors
            are not permitted to call this directly — they use
            extract_and_reconcile_facts instead.
    """
    from ..models import MemoryFact  # noqa: PLC0414

    if actor not in ("user",):
        logger.warning("update_fact called with forbidden actor: %s", actor)
        return None

    fact = db.query(MemoryFact).filter_by(id=fact_id).first()
    if not fact:
        return None

    fact.fact_text = new_text
    fact.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(fact)

    # Re-embed
    delete_fact_vector(db, fact_id)
    insert_fact_vector(db, fact_id, new_text)

    return fact


def delete_fact(db: Session, fact_id: str, *, actor: str = "user") -> bool:
    """Soft-delete a fact: set deleted_at, keep vector/tombstone.

    Args:
        db: SQLAlchemy session.
        fact_id: The fact to delete.
        actor: Must be "user" — auto-memory cannot delete facts.
    """
    from ..models import MemoryFact  # noqa: PLC0414

    if actor not in ("user",):
        logger.warning("delete_fact called with forbidden actor: %s", actor)
        return False

    fact = db.query(MemoryFact).filter_by(id=fact_id).first()
    if not fact:
        return False

    fact.deleted_at = datetime.now(timezone.utc)
    fact.user_locked = True
    fact.updated_at = datetime.now(timezone.utc)
    db.commit()

    # Keep vector for duplicate suppression (tombstone)
    return True


def create_fact(
    db: Session,
    text: str,
    source_chat_id: str | None = None,
    *,
    source: str = "user",
) -> Optional[Any]:
    """Create a user-initiated memory fact (user_locked=true by default)."""
    return _add_fact(db, text, source_chat_id, source=source)
