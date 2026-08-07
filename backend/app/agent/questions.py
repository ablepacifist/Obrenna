"""The ``ask_user`` tool: a typed layer over the pending-request rendezvous.

Lets the agent stop mid-turn and ask a clarifying question instead of guessing,
then continue with the answer in hand. The suspend/resume mechanism (and its
cross-loop subtleties) lives in ``pending.py``; this module only adds the
question vocabulary.

Why mid-turn rather than just ending the turn with a question in prose: the
model often needs the answer to *continue work it has already started* (which
file did you mean, which of these two approaches). Ending the turn would throw
away the tool results and reasoning it has accumulated, and the next message
would restart from cold context. Suspending keeps all of it alive.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from .pending import (
    KIND_QUESTION,
    TIMEOUT,
    PendingRequest,
    create_pending,
    list_pending_for_chat as _list_pending,
    resolve_pending,
    wait_for_response,
)

logger = logging.getLogger(__name__)

# Returned to the model when nobody answers. Phrased as an instruction because
# it lands in the conversation as a tool result -- the model has to do something
# sensible with it rather than wait forever.
NO_ANSWER = (
    "The user did not answer. Do not ask again. Make the most reasonable "
    "assumption, state clearly which assumption you made, and continue."
)

ASK_USER_TOOL_NAME = "ask_user"

# Tool schema. FLAT shape (top-level name/description/parameters) to match the
# other entries in ``allowed_tools`` -- ``_format_tools_for_model`` is what wraps
# these into the OpenAI ``{"type": "function", ...}`` envelope later, and the
# prompt-JSON contract builder reads the flat form directly.
ASK_USER_TOOL_DEF: dict[str, Any] = {
    "name": ASK_USER_TOOL_NAME,
    "description": (
        "Ask the user a clarifying question and WAIT for their answer before "
        "continuing. Use this when the request is genuinely ambiguous and "
        "guessing wrong would waste real work -- for example which of several "
        "matching files they meant, or which of two approaches they want. "
        "Do NOT use it for questions you can answer yourself by reading the "
        "code, for permission to make a change (changes are gated separately), "
        "or to confirm something you were already told."
    ),
    "inputSchema": {
        "type": "object",
        "properties": {
            "question": {
                "type": "string",
                "description": "The question to ask. One specific question, not a list.",
            },
            "options": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "Optional. Suggested answers to offer as one-click choices. "
                    "Give 2-4 concrete options when the answer is a choice "
                    "between known alternatives; omit for open-ended questions."
                ),
            },
        },
        "required": ["question"],
    },
}


async def create_question(
    chat_id: str,
    message_id: str,
    call_id: str,
    question: str,
    options: list[str] | None = None,
) -> PendingRequest:
    """Register a question awaiting an answer (does not wait)."""
    return await create_pending(
        KIND_QUESTION, chat_id, message_id,
        {"call_id": call_id, "question": question, "options": options or []},
    )


async def wait_for_answer(req: PendingRequest, timeout: float = 600.0) -> Optional[str]:
    """Block until answered. Returns the answer, or None if nobody answered."""
    response = await wait_for_response(req, timeout=timeout)
    if response is TIMEOUT or response is None:
        return None
    return str(response)


def resolve_question(question_id: str, answer: str) -> Optional[PendingRequest]:
    """Record an answer and wake the suspended turn.

    Returns the request, or None if the id is unknown (already answered, timed
    out, or its turn ended). Callers should surface that as a 404.
    """
    if not isinstance(answer, str) or not answer.strip():
        raise ValueError("answer must be a non-empty string")
    return resolve_pending(question_id, answer, kind=KIND_QUESTION)


def list_pending_for_chat(chat_id: str) -> list[PendingRequest]:
    """Questions (only) currently blocking this chat's turn."""
    return _list_pending(chat_id, kind=KIND_QUESTION)
