"""Core memory service: budgets, retrieval, context assembly, turn recording, summary folding, fact reconciliation."""
from __future__ import annotations

import json
import logging
import os
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from sqlalchemy.orm import Session

from ..model_runtime.client import chat_completion_sync
from ..model_runtime.config import RuntimeConfig
from ..services.embeddings import embed_text
from ..services.knowledge_packs.config import resolve_pack_paths
from ..services.knowledge_packs.retriever import KnowledgePackRetriever
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
    embed_query,
    insert_fact_vector,
    insert_turn_vector,
    search_facts,
    search_turns,
)
from . import memory_cache
from .memory_versions import (
    bump_account_version,
    bump_chat_version,
    bump_rolling_summary_version,
)

logger = logging.getLogger(__name__)

# ── Knowledge-pack retriever singleton (Fix #7) ──────────────────────────────
# Previously a fresh ``KnowledgePackRetriever`` (opening a fresh sqlite3
# connection per pack) was built every turn. Hold one long-lived retriever that
# pools a connection per pack; rebuild only when the configured pack set changes.

_knowledge_retriever: KnowledgePackRetriever | None = None
_knowledge_retriever_paths: tuple[str, ...] | None = None
_knowledge_retriever_lock = threading.Lock()


def get_knowledge_retriever(
    pack_paths: list[str] | tuple[str, ...],
) -> KnowledgePackRetriever:
    """Return the long-lived retriever for the given pack set, rebuilding on change."""
    global _knowledge_retriever, _knowledge_retriever_paths
    paths_key = tuple(str(Path(p)) for p in pack_paths)
    with _knowledge_retriever_lock:
        if _knowledge_retriever is None or _knowledge_retriever_paths != paths_key:
            if _knowledge_retriever is not None:
                _knowledge_retriever.close()
            # Use the cached query embedder so the query vector is shared with
            # vector_store's fact/turn search within the same turn.
            _knowledge_retriever = KnowledgePackRetriever(pack_paths, embedder=embed_query)
            _knowledge_retriever_paths = paths_key
        return _knowledge_retriever


def reset_knowledge_retriever() -> None:
    """Drop the singleton (tests only). Closes pooled connections."""
    global _knowledge_retriever, _knowledge_retriever_paths
    with _knowledge_retriever_lock:
        if _knowledge_retriever is not None:
            _knowledge_retriever.close()
        _knowledge_retriever = None
        _knowledge_retriever_paths = None

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

# ── Static orchestrator system prompt (Band A, Fix #1) ───────────────────────
# Invariant within a process. Leads the orchestrator message sequence so it is
# byte-stable across turns and Ollama's prefix/KV cache reuses it on turns 2+.
# Kept short and operational to avoid materially changing distilled-orchestrator
# behavior while still giving the model a stable identity/role preamble.
ORCHESTRATOR_STATIC_SYSTEM_PROMPT = (
    "You are Obrenna, a local-first AI assistant running on the user's own hardware. "
    "Answer helpfully, accurately, and concisely. Use the provided memory, past "
    "conversation, and knowledge-pack context when relevant. When tools are available, "
    "call them to ground answers in current factual data rather than guessing. "
    "Prefer plain prose; use Markdown only when it improves clarity."
)


def canonicalise_system_content(content: str) -> str:
    """Normalise a static system-message content string to a byte-stable form.

    Ollama's prefix/KV cache keys on the content tokens, so a byte-stable string
    lets turns 2+ reuse the cached prefix. Per-line trailing whitespace and CRLF
    endings are the likely sources of drift across turns; normalise them and
    strip leading/trailing whitespace.
    """
    if not content:
        return content
    lines = [line.rstrip() for line in content.replace("\r\n", "\n").split("\n")]
    return "\n".join(lines).strip()


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
    """Structured context payload returned by assemble_context.

    Prompt layout (Fix #1) splits the orchestrator's system content into a
    static, cross-turn cacheable band (``to_static_messages``) and a dynamic,
    per-turn memory band (``to_dynamic_messages``). The runtime places the
    static band first so Ollama's prefix/KV cache reuses it across turns; the
    dynamic band (and its ``[mem v=… cv=…]`` version stamp) sits after the
    cacheable prefix so its per-turn variance does not bust the cache.
    """

    def __init__(
        self,
        recency: list[dict] | None = None,
        rolling_summary: str = "",
        facts: list[dict] | None = None,
        archive_turns: list[dict] | None = None,
        knowledge_cards: list[dict] | None = None,
        *,
        account_version: int = 0,
        chat_version: int = 0,
        summary_version: int = 0,
    ):
        self.recency = recency or []
        self.rolling_summary = rolling_summary
        self.facts = facts or []
        self.archive_turns = archive_turns or []
        self.knowledge_cards = knowledge_cards or []
        # Version counters this context was assembled against (Fix #7). Stamped
        # into the dynamic band for diagnostics/telemetry; 0 = unset (EXP0).
        self.account_version = account_version
        self.chat_version = chat_version
        self.summary_version = summary_version

    def _dynamic_parts(self) -> list[str]:
        """The per-turn memory content blocks, in precedence order."""
        parts: list[str] = []

        # 1. Rolling summary always
        if self.rolling_summary:
            parts.append(f"**Context Summary (from previous turns):**\n{self.rolling_summary}")

        # Recency-only mode uses assistant turns directly and intentionally skips
        # vector/archive retrieval for small local orchestrators.
        if self.recency:
            recent_lines = "\n".join(
                f"- {m.get('role', 'assistant')}: {m.get('text', '')}"
                for m in self.recency
            )
            parts.append(f"**Recent conversation context:**\n{recent_lines}")

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

        # 4. Pack knowledge cards (curated workflow/domain guidance)
        if self.knowledge_cards:
            card_lines = []
            for card in self.knowledge_cards:
                card_lines.append(
                    f"- [{card.get('card_type', 'card')}] {card.get('topic', '')}: {card.get('content', '')}"
                )
            parts.append(f"**Retrieved knowledge packs:**\n" + "\n".join(card_lines))

        # Only include markdown hint when there's actual context content
        if parts:
            parts.append(
                "You may use Markdown formatting in your responses (headers, bold, lists, "
                "code blocks, tables) when it improves readability. Plain prose is fine when "
                "markdown would add no value."
            )

        return parts

    def to_static_messages(self) -> list[dict]:
        """Band A: invariant orchestrator identity/role/rules prompt (Fix #1).

        Constant within a process and byte-stable, so Ollama's prefix cache
        reuses it across turns. Leads the message sequence.
        """
        return [
            {
                "role": "system",
                "content": canonicalise_system_content(ORCHESTRATOR_STATIC_SYSTEM_PROMPT),
            }
        ]

    def to_dynamic_messages(self) -> list[dict]:
        """Band B: per-turn memory block as ONE system message, version-stamped (Fix #1).

        The first line ``[mem v=<account_version> cv=<chat_version>]`` is a
        diagnostics/telemetry stamp. This band sits AFTER the cacheable static
        bands, so its per-turn variance does not bust the prefix cache.
        """
        parts = self._dynamic_parts()
        if not parts:
            return []
        stamp = f"[mem v={self.account_version} cv={self.chat_version}]"
        content = canonicalise_system_content(stamp + "\n\n" + "\n\n".join(parts))
        return [{"role": "system", "content": content}]

    def to_messages(self) -> list[dict]:
        """Backward-compatible dynamic memory block (unstamped, no static prompt).

        Retained for ``build_model_messages`` and tests. Production orchestration
        uses ``to_static_messages()`` + ``to_dynamic_messages()`` instead so the
        static band can lead and be prefix-cached.
        """
        parts = self._dynamic_parts()
        if not parts:
            return []
        return [{"role": "system", "content": "\n\n".join(parts)}]


def _build_recency(db: Session, chat_id: str, recent_count: int) -> list[dict]:
    """Last N assistant messages before this turn, oldest-first."""
    from ..models import ChatMessage  # noqa: PLC0414

    recency: list[dict] = []
    all_msgs = (
        db.query(ChatMessage)
        .filter_by(chat_id=chat_id)
        .filter(ChatMessage.role == "assistant")
        .order_by(ChatMessage.created_at.desc())
        .limit(recent_count)
        .all()
    )
    for m in reversed(all_msgs):
        recency.append({"role": "assistant", "text": m.text})
    return recency


def _pack_signature(pack_paths: list[str]) -> tuple[tuple[str, int], ...]:
    """Stable signature of the configured pack set: ((path, mtime), ...).

    A pack file replaced on disk changes its mtime, which changes the
    assembled-context cache key even though no in-DB version counter bumped
    (packs are external files outside the versioned write path).
    """
    sig: list[tuple[str, int]] = []
    for p in pack_paths:
        try:
            mtime = int(os.path.getmtime(str(p)))
        except OSError:
            mtime = -1
        sig.append((str(p), mtime))
    return tuple(sig)


def assemble_context(
    db: Session,
    chat: Any,
    user_message: str,
    *,
    recent_count: int = 6,
    memory_mode: str = "default",
    max_context_chars: int | None = None,
) -> MemoryContext:
    """Build memory context for a chat turn.

    Precedence: recency buffer → rolling summary → facts → archive turns.

    Retrieval is cached by a composite version key (Fix #7). On a cache hit
    the full retrieval (recency DB scan, vector search over facts/turns,
    knowledge-pack search, all embedding work) is skipped. The key includes
    the account-memory version, chat-memory version, rolling-summary version,
    the query hash, and the pack-file mtime signature — so any write that
    changes the context atomically invalidates it. We never ship an
    unversioned cache: a missing version counter falls through to a full
    rebuild.

    The account-memory-version counter is the correctness guard for
    user_locked facts: any ADD/UPDATE/DELETE of a locked fact bumps it, so the
    cached facts block can never serve a stale locked fact — the next turn
    re-reads locked facts fresh after a locked-fact edit.
    """
    from ..models import ChatTurn, MemoryFact  # noqa: PLC0414
    from .memory_versions import (  # noqa: PLC0414
        get_account_version,
        get_chat_version,
        get_rolling_summary_version,
    )

    chat_id = chat.id

    # EXP0 lightweight path: recency only, never cached (no version counters).
    if memory_mode == "exp0_recency_only":
        recency = _build_recency(db, chat_id, recent_count)
        return _cap_recency_context(MemoryContext(recency=recency), max_context_chars or 4000)

    # ── Version-keyed cache lookup ──────────────────────────────────────────
    account_version = get_account_version(db, MemoryFact.ACCOUNT_ID)
    chat_version = get_chat_version(db, chat_id)
    summary_version = get_rolling_summary_version(db, chat_id)
    qhash = memory_cache.query_hash(user_message)
    pack_paths = resolve_pack_paths()
    pack_sig = _pack_signature(pack_paths)
    cache_key = memory_cache.make_context_key(
        chat_id, chat_version, summary_version, account_version,
        qhash, memory_mode, max_context_chars, pack_sig,
    )
    cached = memory_cache.get_context(cache_key)
    if cached is not None:
        return cached

    # ── Full retrieval (cache miss) ─────────────────────────────────────────
    recency = _build_recency(db, chat_id, recent_count)

    # Rolling summary
    rolling_summary = getattr(chat, "rolling_summary", "") or ""

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
    facts_top_k = TIGHT_FACT_TOP_K if budget_tokens < 4096 else get_default_top_k()

    # Memory facts. user_locked means "protected from auto-overwrite/delete"
    # (see _reconcile_fact), NOT "hidden from retrieval" — excluding locked
    # facts here meant a user's own explicitly-created memories (which
    # default to user_locked=True, see _add_fact) were never surfaced to the
    # orchestrator, only auto-extracted ones. Soft-deleted facts are still
    # excluded via exclude_deleted (deletion also sets user_locked=True as a
    # tombstone marker, but deleted_at is the authoritative deletion flag).
    facts = search_facts(db, user_message, top_k=facts_top_k, exclude_locked=False)
    facts_out = [{"id": f[0], "text": f[2]} for f in facts]

    archive_scores = search_turns(db, chat_id, user_message, top_k=archive_top_k * 2)
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

    knowledge_cards: list[dict] = []
    try:
        if pack_paths:
            retriever = get_knowledge_retriever(pack_paths)
            knowledge_context = retriever.search(
                user_message,
                max_cards=4,
                max_tokens=max(256, budget_tokens // 2),
            )
            knowledge_cards = [card.as_dict() for card in knowledge_context.cards]
    except Exception as exc:
        logger.warning("Knowledge pack retrieval failed: %s", exc)

    ctx = MemoryContext(
        recency=recency,
        rolling_summary=rolling_summary,
        facts=facts_out,
        archive_turns=archive_out,
        knowledge_cards=knowledge_cards,
        account_version=account_version,
        chat_version=chat_version,
        summary_version=summary_version,
    )
    memory_cache.set_context(cache_key, ctx)
    return ctx


def _cap_recency_context(context: MemoryContext, max_chars: int) -> MemoryContext:
    """Trim recency-only EXP0 context to a small deterministic character budget."""
    remaining = max_chars
    capped: list[dict] = []
    for msg in reversed(context.recency):
        text = str(msg.get("text", ""))
        if remaining <= 0:
            break
        trimmed = text[-remaining:]
        remaining -= len(trimmed)
        capped.append({"role": msg.get("role", "assistant"), "text": trimmed})
    capped.reverse()
    return MemoryContext(recency=capped)


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
        # Bump the chat-memory version in the SAME transaction as the turn
        # write so the assembled-context cache invalidates atomically (Fix #7).
        # A new turn changes the recency buffer and archived-turn search results.
        bump_chat_version(db, chat.id)
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
        # Bump the rolling-summary version in the same transaction so the
        # assembled-context cache invalidates when the summary text changes (Fix #7).
        bump_rolling_summary_version(db, chat.id)
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
                    # Bump the fact's own version (per-row embedding cache
                    # invalidation) and the account version (facts block /
                    # assembled-context cache invalidation) in this same
                    # transaction, committed below (Fix #7).
                    best_match.version = int(getattr(best_match, "version", 1) or 1) + 1
                    bump_account_version(db, best_match.account_id)
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
    # Bump the account-memory version in the same transaction as the fact
    # write so the facts block / assembled-context cache invalidates
    # atomically (Fix #7). This also covers user_locked facts: a user-created
    # fact is user_locked=True by default, and bumping here means the very next
    # turn re-reads it fresh rather than serving a stale cached facts block.
    # ``fact.account_id`` is a Python-side default applied at flush, so it is
    # still None here — fall back to the account constant.
    bump_account_version(db, fact.account_id or MemoryFact.ACCOUNT_ID)
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
    # Bump the fact's own version (per-row embedding cache invalidation) and
    # the account version (facts block / assembled-context cache invalidation)
    # in the same transaction (Fix #7).
    fact.version = int(getattr(fact, "version", 1) or 1) + 1
    bump_account_version(db, fact.account_id)
    db.commit()
    db.refresh(fact)

    # Re-embed (delete_fact_vector also drops the cached per-row vector).
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
    # Bump the fact's own version + account version in this transaction so the
    # next turn does not serve the deleted fact from cache (Fix #7).
    fact.version = int(getattr(fact, "version", 1) or 1) + 1
    bump_account_version(db, fact.account_id)
    db.commit()

    # Drop the cached per-row embedding (tombstone vector is kept in the store
    # for duplicate suppression).
    delete_fact_vector(db, fact_id)
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
