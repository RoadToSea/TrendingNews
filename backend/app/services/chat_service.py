"""AI floating chat service handling prompt templates, SSE streaming with keepalives, and DB report export."""

import asyncio
from datetime import datetime
import json
from typing import Any, AsyncIterator, Dict, List, Optional
import zoneinfo

from app.models import (
    ChatContextItem,
    ChatMessageDTO,
    ChatMessagesResponse,
    ChatSessionCreateRequest,
    ChatSessionDTO,
    ChatStreamRequest,
    PromptTemplateCreateRequest,
    PromptTemplateDTO,
    PromptTemplateUpdateRequest,
    ReportDTO,
    SaveChatReportRequest,
)
from app.repositories.chat_repo import ChatRepository
from app.repositories.report_repo import ReportRepository
from app.services.ai_gateway.base import LLMGatewayError, StreamEvent
from app.services.ai_gateway.gateway_service import AIGatewayService
from app.services.report_prompts import REPORT_SYSTEM_PROMPT, build_chat_export_prompt

_KEEPALIVE_INTERVAL_SEC = 15.0


class ChatNotFoundError(Exception):
    """Raised when a chat session or prompt template cannot be found."""


class PromptConflictError(Exception):
    """Raised when a prompt template name collides with an existing template."""


def _format_sse_event(event_name: str, payload: Dict[str, Any]) -> str:
    return f"event: {event_name}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


_KIND_LABELS = {
    "event": "热点事件",
    "news": "新闻报道",
    "rss": "媒体订阅",
    "report": "历史报告",
}


def _format_context_block(items: List[ChatContextItem]) -> str:
    if not items:
        return ""
    lines = ["[已选参考上下文]"]
    for idx, item in enumerate(items, start=1):
        kind_label = _KIND_LABELS.get(item.kind, "参考资料")
        lines.append(f"{idx}. 【{kind_label} · {item.platform_or_domain}】{item.title}")
        if item.snapshot_text:
            lines.append(f"   摘要: {item.snapshot_text[:280]}")
        if item.url:
            lines.append(f"   链接: {item.url}")
    return "\n".join(lines)


class ChatService:
    """Service layer managing prompt templates, SSE chat sessions, and report persistence."""

    def __init__(
        self,
        chat_repo: ChatRepository,
        report_repo: ReportRepository,
        gateway_service: AIGatewayService,
        timezone_name: str,
    ) -> None:
        """Initialize the chat service.

        Args:
            chat_repo: Chat, prompt template, and provider repository.
            report_repo: Report repository receiving exported chat summaries.
            gateway_service: AI gateway resolving model adapters.
            timezone_name: Application timezone name.
        """
        self._repo = chat_repo
        self._reports = report_repo
        self._gateway = gateway_service
        self._tz = zoneinfo.ZoneInfo(timezone_name)

    def _now(self) -> datetime:
        return datetime.now(self._tz)

    def _now_iso(self) -> str:
        return self._now().isoformat(timespec="seconds")

    # ---- Prompt Templates ----

    def list_prompts(self) -> List[PromptTemplateDTO]:
        """List all opening prompt templates.

        Returns:
            List[PromptTemplateDTO]: Templates sorted by default flag then ID.
        """
        return [PromptTemplateDTO(**row) for row in self._repo.list_prompt_templates()]

    def create_prompt(self, req: PromptTemplateCreateRequest) -> PromptTemplateDTO:
        """Create a new prompt template.

        Args:
            req: Validated prompt template payload.

        Returns:
            PromptTemplateDTO: Stored template record.

        Raises:
            PromptConflictError: When a template with the same name already exists.
        """
        name = req.name.strip()
        if any(t["name"] == name for t in self._repo.list_prompt_templates()):
            raise PromptConflictError(f"Prompt template '{name}' already exists")
        row = self._repo.create_prompt_template(
            name=name,
            category=req.category.strip() or "chat_system",
            content=req.content.strip(),
            is_default=req.is_default,
            is_enabled=req.is_enabled,
            now_iso=self._now_iso(),
        )
        return PromptTemplateDTO(**row)

    def update_prompt(self, template_id: int, req: PromptTemplateUpdateRequest) -> PromptTemplateDTO:
        """Update an existing prompt template.

        Args:
            template_id: Template primary key.
            req: Partial update payload.

        Returns:
            PromptTemplateDTO: Updated template DTO.

        Raises:
            ChatNotFoundError: If `template_id` does not exist.
            PromptConflictError: If renamed to an existing template name.
        """
        existing = self._repo.get_prompt_template(template_id)
        if existing is None:
            raise ChatNotFoundError(f"Prompt template {template_id} not found")

        new_name = req.name.strip() if req.name is not None else str(existing["name"])
        for row in self._repo.list_prompt_templates():
            if row["name"] == new_name and int(row["id"]) != template_id:
                raise PromptConflictError(f"Prompt template '{new_name}' already exists")

        updated = self._repo.update_prompt_template(
            template_id,
            name=new_name,
            content=req.content.strip() if req.content is not None else str(existing["content"]),
            is_default=req.is_default if req.is_default is not None else bool(existing["is_default"]),
            is_enabled=req.is_enabled if req.is_enabled is not None else bool(existing["is_enabled"]),
            now_iso=self._now_iso(),
        )
        if updated is None:
            raise ChatNotFoundError(f"Prompt template {template_id} not found")
        return PromptTemplateDTO(**updated)

    def delete_prompt(self, template_id: int) -> None:
        """Delete a prompt template by ID.

        Args:
            template_id: Template primary key.

        Raises:
            ChatNotFoundError: If template does not exist.
        """
        if not self._repo.delete_prompt_template(template_id):
            raise ChatNotFoundError(f"Prompt template {template_id} not found")

    # ---- Chat Sessions ----

    def list_sessions(self, user_id: int) -> List[ChatSessionDTO]:
        """List persistent chat sessions owned by `user_id`.

        Args:
            user_id: Authenticated user ID.

        Returns:
            List[ChatSessionDTO]: Session DTOs ordered by most recent update.
        """
        return [ChatSessionDTO(**row) for row in self._repo.list_sessions(user_id)]

    def create_session(self, user_id: int, req: ChatSessionCreateRequest) -> ChatSessionDTO:
        """Create a new persistent chat session.

        Args:
            user_id: Authenticated owner user ID.
            req: Session creation options.

        Returns:
            ChatSessionDTO: Newly created session DTO.
        """
        prompt_id = req.prompt_template_id
        if prompt_id is None:
            default_tpl = self._repo.get_default_prompt_template()
            prompt_id = int(default_tpl["id"]) if default_tpl else None
        row = self._repo.create_session(
            user_id=user_id,
            title=req.title.strip() or "新对话",
            provider_slot_id=req.provider_slot_id,
            prompt_template_id=prompt_id,
            now_iso=self._now_iso(),
        )
        return ChatSessionDTO(**row)

    def delete_session(self, session_id: int, user_id: int) -> None:
        """Delete a chat session owned by `user_id`.

        Args:
            session_id: Session ID.
            user_id: Authenticated user ID.

        Raises:
            ChatNotFoundError: If session does not exist or belongs to another user.
        """
        if not self._repo.delete_session(session_id, user_id):
            raise ChatNotFoundError(f"Chat session {session_id} not found")

    def get_session_messages(self, session_id: int, user_id: int) -> ChatMessagesResponse:
        """Load session metadata and chronological message history.

        Args:
            session_id: Target session ID.
            user_id: Owner user ID check.

        Returns:
            ChatMessagesResponse: Session metadata and messages with context chips.

        Raises:
            ChatNotFoundError: If session is missing or unauthorized.
        """
        session = self._require_user_session(session_id, user_id)
        messages = self._repo.list_messages(session_id)
        return ChatMessagesResponse(
            session=ChatSessionDTO(**session),
            messages=[ChatMessageDTO(**m) for m in messages],
        )

    def _require_user_session(self, session_id: int, user_id: int) -> Dict[str, Any]:
        session = self._repo.get_session(session_id)
        if session is None or int(session["user_id"]) != user_id:
            raise ChatNotFoundError(f"Chat session {session_id} not found")
        return session

    def _resolve_system_prompt(self, template_id: Optional[int]) -> str:
        tpl = self._repo.get_prompt_template(template_id) if template_id is not None else None
        if tpl is None:
            tpl = self._repo.get_default_prompt_template()
        return str(tpl["content"]) if tpl and tpl.get("is_enabled", True) else ""

    async def stream_message(
        self,
        session_id: int,
        user_id: int,
        req: ChatStreamRequest,
    ) -> AsyncIterator[str]:
        """Persist user turn, stream LLM reply with 15s SSE keepalives, and save assistant response.

        Args:
            session_id: Target session ID.
            user_id: Authenticated user ID.
            req: User message text, attached picker context items, and optional slot/prompt overrides.

        Yields:
            str: Formatted SSE frames (`event: init|delta|done|error` or `: keepalive\\n\\n`).

        Raises:
            ChatNotFoundError: Before streaming starts if session is not owned by `user_id`.
        """
        session = self._require_user_session(session_id, user_id)
        chosen_slot_id = req.provider_slot_id or session.get("provider_slot_id")
        chosen_prompt_id = req.prompt_template_id if req.prompt_template_id is not None else session.get("prompt_template_id")

        try:
            slot, adapter = self._gateway.resolve_slot(
                slot_id=chosen_slot_id,
                role="chat_default",
                fallback_any=chosen_slot_id is None,
            )
        except LLMGatewayError as exc:
            yield _format_sse_event("error", {"code": exc.code, "message": exc.message})
            return

        now_iso = self._now_iso()
        context_dicts = [item.model_dump() for item in req.context_items]
        self._repo.add_message(
            session_id=session_id,
            role="user",
            content=req.content,
            context_items=context_dicts,
            usage={},
            now_iso=now_iso,
        )

        # Keep external_conversation_id only if staying on the same slot; reset when user switches slots.
        ext_conv_id = (
            str(session.get("external_conversation_id") or "")
            if session.get("provider_slot_id") in (None, int(slot["id"]))
            else ""
        )
        history_rows = self._repo.list_messages(session_id)
        llm_messages = self._build_llm_messages(history_rows)
        system_prompt = self._resolve_system_prompt(chosen_prompt_id)

        async for frame in self._drive_stream_with_keepalive(
            session=session,
            session_id=session_id,
            slot=slot,
            adapter=adapter,
            llm_messages=llm_messages,
            system_prompt=system_prompt,
            ext_conv_id=ext_conv_id,
            chosen_prompt_id=chosen_prompt_id,
            first_user_text=req.content,
        ):
            yield frame

    async def _drive_stream_with_keepalive(
        self,
        *,
        session: Dict[str, Any],
        session_id: int,
        slot: Dict[str, Any],
        adapter: Any,
        llm_messages: List[Dict[str, str]],
        system_prompt: str,
        ext_conv_id: str,
        chosen_prompt_id: Optional[int],
        first_user_text: str,
    ) -> AsyncIterator[str]:
        queue: asyncio.Queue[Optional[StreamEvent | BaseException]] = asyncio.Queue()

        async def _producer() -> None:
            try:
                async for ev in adapter.stream_chat(
                    messages=llm_messages,
                    model=str(slot["model"]),
                    system_prompt=system_prompt,
                    external_conversation_id=ext_conv_id,
                    extra_params=dict(slot.get("extra_params") or {}),
                ):
                    await queue.put(ev)
            except BaseException as exc:
                await queue.put(exc)
            finally:
                await queue.put(None)

        producer_task = asyncio.create_task(_producer())
        accumulated: List[str] = []
        observed_conv_id = ext_conv_id
        init_sent = False

        try:
            while True:
                try:
                    item = await asyncio.wait_for(queue.get(), timeout=_KEEPALIVE_INTERVAL_SEC)
                except asyncio.TimeoutError:
                    # Heartbeat keeps upstream reverse proxies (e.g., Cloudflare 100s timeout) open.
                    yield ": keepalive\n\n"
                    continue

                if item is None:
                    break
                if isinstance(item, LLMGatewayError):
                    yield _format_sse_event("error", {"code": item.code, "message": item.message})
                    return
                if isinstance(item, BaseException):
                    yield _format_sse_event("error", {"code": "stream_error", "message": str(item)})
                    return

                if item.conversation_id:
                    observed_conv_id = item.conversation_id

                if item.type == "init":
                    if not init_sent:
                        init_sent = True
                        yield _format_sse_event(
                            "init",
                            {"session_id": session_id, "external_conversation_id": observed_conv_id},
                        )
                elif item.type == "delta" and item.text:
                    if not init_sent:
                        init_sent = True
                        yield _format_sse_event(
                            "init",
                            {"session_id": session_id, "external_conversation_id": observed_conv_id},
                        )
                    accumulated.append(item.text)
                    yield _format_sse_event("delta", {"text": item.text})
                elif item.type == "done":
                    final_text = "".join(accumulated).strip()
                    saved_msg = self._finalize_turn(
                        session=session,
                        session_id=session_id,
                        slot_id=int(slot["id"]),
                        prompt_id=chosen_prompt_id,
                        ext_conv_id=observed_conv_id,
                        first_user_text=first_user_text,
                        assistant_text=final_text,
                        usage=item.usage,
                    )
                    yield _format_sse_event(
                        "done",
                        {"message_id": int(saved_msg["id"]), "usage": item.usage},
                    )
        finally:
            if not producer_task.done():
                producer_task.cancel()

    def _finalize_turn(
        self,
        *,
        session: Dict[str, Any],
        session_id: int,
        slot_id: int,
        prompt_id: Optional[int],
        ext_conv_id: str,
        first_user_text: str,
        assistant_text: str,
        usage: Dict[str, Any],
    ) -> Dict[str, Any]:
        now_iso = self._now_iso()
        new_title = None
        if str(session.get("title") or "").strip() in ("", "新对话") and first_user_text.strip():
            new_title = first_user_text.strip().replace("\n", " ")[:40]
        self._repo.update_session_state(
            session_id,
            title=new_title,
            provider_slot_id=slot_id,
            external_conversation_id=ext_conv_id,
            prompt_template_id=prompt_id,
            now_iso=now_iso,
        )
        return self._repo.add_message(
            session_id=session_id,
            role="assistant",
            content=assistant_text,
            context_items=[],
            usage=usage,
            now_iso=now_iso,
        )

    @staticmethod
    def _build_llm_messages(history_rows: List[Dict[str, Any]]) -> List[Dict[str, str]]:
        messages: List[Dict[str, str]] = []
        for row in history_rows:
            role = str(row["role"])
            text = str(row["content"])
            raw_ctx = row.get("context_items") or []
            if raw_ctx and role == "user":
                parsed_ctx = [ChatContextItem(**c) for c in raw_ctx if isinstance(c, dict)]
                ctx_block = _format_context_block(parsed_ctx)
                if ctx_block:
                    text = f"{ctx_block}\n\n[用户问题]\n{text}"
            messages.append({"role": role, "content": text})
        return messages

    async def save_report_from_session(
        self,
        session_id: int,
        user_id: int,
        req: SaveChatReportRequest,
    ) -> ReportDTO:
        """Distill or format a chat session directly into SQLite `reports` without touching host files.

        Args:
            session_id: Originating chat session ID.
            user_id: Authenticated user ID.
            req: Export parameters (`title`, `message_ids`, `auto_summarize`, etc.).

        Returns:
            ReportDTO: Saved report record (`report_type='chat_generated'`).

        Raises:
            ChatNotFoundError: If session does not exist or has no matching messages.
        """
        session = self._require_user_session(session_id, user_id)
        messages = (
            self._repo.list_messages_by_ids(session_id, req.message_ids)
            if req.message_ids
            else self._repo.list_messages(session_id)
        )
        if not messages:
            raise ChatNotFoundError("No chat messages selected to export as report")

        event_ids: List[int] = []
        news_ids: List[int] = []
        transcript_lines: List[str] = []
        for msg in messages:
            speaker = "用户" if msg["role"] == "user" else "AI 助手"
            transcript_lines.append(f"### {speaker}\n{msg['content']}")
            for ctx in msg.get("context_items") or []:
                if isinstance(ctx, dict) and isinstance(ctx.get("id"), int):
                    if ctx.get("kind") == "event" and ctx["id"] not in event_ids:
                        event_ids.append(ctx["id"])
                    elif ctx.get("kind") == "news" and ctx["id"] not in news_ids:
                        news_ids.append(ctx["id"])

        transcript = "\n\n".join(transcript_lines)
        used_slot_id: Optional[int] = session.get("provider_slot_id")
        content_md = transcript

        if req.auto_summarize:
            try:
                slot, adapter = self._gateway.resolve_slot(
                    slot_id=req.provider_slot_id or used_slot_id,
                    role="summary_report",
                    fallback_any=True,
                )
                used_slot_id = int(slot["id"])
                chunks: List[str] = []
                async for ev in adapter.stream_chat(
                    messages=[{"role": "user", "content": build_chat_export_prompt(transcript)}],
                    model=str(slot["model"]),
                    system_prompt=REPORT_SYSTEM_PROMPT,
                    extra_params=dict(slot.get("extra_params") or {}),
                ):
                    if ev.type == "delta" and ev.text:
                        chunks.append(ev.text)
                summarized = "".join(chunks).strip()
                if summarized:
                    content_md = summarized
            except LLMGatewayError:
                # Fall back cleanly to clean transcript formatting when no summary AI slot is configured.
                content_md = f"# 对话研判纪要\n\n{transcript}"

        now = self._now()
        report_title = (req.title or "").strip() or f"对话研判报告：{session['title']}"
        saved = self._reports.create(
            report_type="chat_generated",
            report_date=req.report_date or now.date().isoformat(),
            domain=req.domain.strip(),
            title=report_title,
            content_md=content_md,
            related_event_ids=event_ids,
            related_news_ids=news_ids,
            source_session_id=session_id,
            provider_slot_id=used_slot_id,
            now_iso=now.isoformat(timespec="seconds"),
        )
        return ReportDTO(**saved)