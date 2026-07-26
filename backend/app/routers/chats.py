"""CRUD for chats and folders (sidebar persistence)."""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Chat, ChatMessage, Folder
from ..schemas.api import (
    ChatDTO,
    ChatDetailDTO,
    ChatMessageDTO,
    CreateChatRequest,
    CreateFolderRequest,
    FolderDTO,
    UpdateChatRequest,
    UpdateFolderRequest,
)

router = APIRouter()
logger = logging.getLogger(__name__)


# --- folders -----------------------------------------------------------------

@router.get("/api/folders", response_model=list[FolderDTO])
def list_folders(db: Session = Depends(get_db)):
    rows = db.execute(select(Folder).order_by(Folder.created_at)).scalars().all()
    return [FolderDTO(id=r.id, name=r.name, created_at=r.created_at.isoformat()) for r in rows]


@router.post("/api/folders", response_model=FolderDTO)
def create_folder(payload: CreateFolderRequest, db: Session = Depends(get_db)):
    folder = Folder(id=uuid.uuid4().hex, name=payload.name)
    db.add(folder)
    db.commit()
    db.refresh(folder)
    return FolderDTO(id=folder.id, name=folder.name, created_at=folder.created_at.isoformat())


@router.patch("/api/folders/{folder_id}", response_model=FolderDTO)
def rename_folder(folder_id: str, payload: UpdateFolderRequest, db: Session = Depends(get_db)):
    folder = db.get(Folder, folder_id)
    if not folder:
        raise HTTPException(status_code=404, detail="Folder not found.")
    folder.name = payload.name
    db.commit()
    db.refresh(folder)
    return FolderDTO(id=folder.id, name=folder.name, created_at=folder.created_at.isoformat())


@router.delete("/api/folders/{folder_id}", status_code=204)
def delete_folder(folder_id: str, db: Session = Depends(get_db)):
    folder = db.get(Folder, folder_id)
    if not folder:
        raise HTTPException(status_code=404, detail="Folder not found.")
    db.delete(folder)
    db.commit()


# --- chats -------------------------------------------------------------------

def _chat_dto(chat: Chat) -> ChatDTO:
    return ChatDTO(
        id=chat.id,
        title=chat.title,
        folder_id=chat.folder_id,
        active_codebase_project_id=chat.active_codebase_project_id,
        created_at=chat.created_at.isoformat(),
        updated_at=chat.updated_at.isoformat(),
    )


def _msg_dto(msg: ChatMessage) -> ChatMessageDTO:
    return ChatMessageDTO(
        id=msg.id,
        role=msg.role,
        text=msg.text,
        artifacts=msg.artifacts or [],
        files=msg.files or [],
        tool_events=getattr(msg, "tool_events", None) or [],
        created_at=msg.created_at.isoformat(),
    )


@router.get("/api/chats", response_model=list[ChatDTO])
def list_chats(db: Session = Depends(get_db)):
    rows = db.execute(select(Chat).order_by(Chat.updated_at.desc())).scalars().all()
    return [_chat_dto(r) for r in rows]


@router.post("/api/chats", response_model=ChatDTO)
def create_chat(payload: CreateChatRequest, db: Session = Depends(get_db)):
    chat = Chat(
        id=uuid.uuid4().hex,
        title=payload.title,
        folder_id=payload.folder_id,
    )
    db.add(chat)
    db.commit()
    db.refresh(chat)
    return _chat_dto(chat)


@router.get("/api/chats/{chat_id}", response_model=ChatDetailDTO)
def get_chat(chat_id: str, db: Session = Depends(get_db)):
    chat = db.get(Chat, chat_id)
    if not chat:
        raise HTTPException(status_code=404, detail="Chat not found.")
    return ChatDetailDTO(
        **_chat_dto(chat).model_dump(),
        messages=[_msg_dto(m) for m in chat.messages],
    )


@router.patch("/api/chats/{chat_id}", response_model=ChatDTO)
def update_chat(chat_id: str, payload: UpdateChatRequest, db: Session = Depends(get_db)):
    chat = db.get(Chat, chat_id)
    if not chat:
        raise HTTPException(status_code=404, detail="Chat not found.")
    if payload.title is not None:
        chat.title = payload.title
    if payload.unfile:
        chat.folder_id = None
    elif payload.folder_id is not None:
        chat.folder_id = payload.folder_id
    if payload.clear_codebase_project:
        chat.active_codebase_project_id = None
    elif payload.active_codebase_project_id is not None:
        chat.active_codebase_project_id = payload.active_codebase_project_id
    chat.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(chat)
    return _chat_dto(chat)


@router.delete("/api/chats/{chat_id}", status_code=204)
def delete_chat(chat_id: str, db: Session = Depends(get_db)):
    logger.info("DELETE CHAT REQUEST: chat_id=%s", chat_id)
    chat = db.get(Chat, chat_id)
    if not chat:
        logger.warning("Chat not found for deletion: chat_id=%s", chat_id)
        raise HTTPException(status_code=404, detail="Chat not found.")
    # Delete all messages for this chat (cascade handles it, but log explicitly)
    msg_count = db.query(ChatMessage).filter_by(chat_id=chat_id).count()
    logger.info("Deleting chat %s with %d messages", chat_id, msg_count)
    db.delete(chat)
    db.commit()
    logger.info("CHAT DELETED: chat_id=%s", chat_id)
