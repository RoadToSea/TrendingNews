"""AI floating chat session CRUD, SSE streaming, and save-as-report API endpoints."""

from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse

from app.api.deps import get_chat_service, get_current_user
from app.models import (
    ChatMessagesResponse,
    ChatSessionCreateRequest,
    ChatSessionDTO,
    ChatStreamRequest,
    ReportDTO,
    SaveChatReportRequest,
)
from app.repositories.user_repo import UserRecord
from app.services.ai_gateway.base import LLMGatewayError
from app.services.chat_service import ChatNotFoundError, ChatService

router = APIRouter(prefix="/api/chat", tags=["chat"])


@router.get("/sessions", response_model=List[ChatSessionDTO])
def list_sessions(
    current_user: UserRecord = Depends(get_current_user),
    chat_service: ChatService = Depends(get_chat_service),
) -> List[ChatSessionDTO]:
    """List persistent chat sessions owned by the current user."""
    return chat_service.list_sessions(current_user.id)


@router.post("/sessions", response_model=ChatSessionDTO)
def create_session(
    body: ChatSessionCreateRequest,
    current_user: UserRecord = Depends(get_current_user),
    chat_service: ChatService = Depends(get_chat_service),
) -> ChatSessionDTO:
    """Create a new chat session with optional provider slot and prompt template bindings."""
    return chat_service.create_session(current_user.id, body)


@router.delete("/sessions/{session_id}")
def delete_session(
    session_id: int,
    current_user: UserRecord = Depends(get_current_user),
    chat_service: ChatService = Depends(get_chat_service),
) -> dict:
    """Delete a chat session and its message history."""
    try:
        chat_service.delete_session(session_id, current_user.id)
    except ChatNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return {"ok": True}


@router.get("/sessions/{session_id}/messages", response_model=ChatMessagesResponse)
def get_session_messages(
    session_id: int,
    current_user: UserRecord = Depends(get_current_user),
    chat_service: ChatService = Depends(get_chat_service),
) -> ChatMessagesResponse:
    """Load session metadata and full message history including picker context chips."""
    try:
        return chat_service.get_session_messages(session_id, current_user.id)
    except ChatNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.post("/sessions/{session_id}/stream")
async def stream_chat(
    session_id: int,
    body: ChatStreamRequest,
    current_user: UserRecord = Depends(get_current_user),
    chat_service: ChatService = Depends(get_chat_service),
) -> StreamingResponse:
    """Stream an AI assistant reply over Server-Sent Events with anti-buffering headers."""
    try:
        # Validate session ownership eagerly so invalid IDs fail with HTTP 404 instead of SSE 200.
        chat_service.get_session_messages(session_id, current_user.id)
    except ChatNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    return StreamingResponse(
        chat_service.stream_message(session_id, current_user.id, body),
        media_type="text/event-stream; charset=utf-8",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/sessions/{session_id}/save-report", response_model=ReportDTO)
async def save_chat_as_report(
    session_id: int,
    body: SaveChatReportRequest,
    current_user: UserRecord = Depends(get_current_user),
    chat_service: ChatService = Depends(get_chat_service),
) -> ReportDTO:
    """Export selected or full session dialogue into the SQLite `reports` table."""
    try:
        return await chat_service.save_report_from_session(session_id, current_user.id, body)
    except ChatNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except LLMGatewayError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc