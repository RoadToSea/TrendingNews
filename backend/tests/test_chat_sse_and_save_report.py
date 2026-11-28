"""Tests for prompt templates, chat sessions, SSE streaming, and saving chat reports."""

import json
from typing import Any, AsyncIterator, Dict, List

from fastapi.testclient import TestClient

from app.services.ai_gateway.base import StreamEvent


class _FakeChatGateway:
    async def stream_chat(
        self,
        messages: List[Dict[str, str]],
        model: str,
        *,
        system_prompt: str = "",
        external_conversation_id: str = "",
        extra_params: Dict[str, Any] | None = None,
    ) -> AsyncIterator[StreamEvent]:
        last_user = messages[-1]["content"]
        conv = external_conversation_id or "conv-chat-777"
        yield StreamEvent(type="init", conversation_id=conv)
        if "整理" in last_user and "Markdown" in last_user:
            yield StreamEvent(type="delta", text="# 对话提炼分析报告\n\n已将选中新闻讨论整理归档。")
        else:
            yield StreamEvent(type="delta", text="第一段分析：")
            yield StreamEvent(type="delta", text="AI 芯片引发广泛关注。")
        yield StreamEvent(type="done", conversation_id=conv, usage={"output_tokens": 18})

    async def complete_json(self, *args, **kwargs):
        return {"ok": True}, {}


def test_prompt_template_crud_and_single_default(auth_client: TestClient) -> None:
    initial = auth_client.get("/api/prompts").json()
    assert len(initial) == 1
    assert initial[0]["is_default"] is True

    created = auth_client.post(
        "/api/prompts",
        json={
            "name": "金融快讯模式",
            "content": "重点提炼二级市场估值影响与风险。",
            "is_default": True,
            "is_enabled": True,
        },
    )
    assert created.status_code == 200
    new_id = created.json()["id"]

    # Setting new template as default clears default flag on the earlier template
    all_tpls = auth_client.get("/api/prompts").json()
    defaults = [t for t in all_tpls if t["is_default"]]
    assert len(defaults) == 1
    assert defaults[0]["id"] == new_id

    upd = auth_client.put(f"/api/prompts/{new_id}", json={"name": "宏观与金融研判"})
    assert upd.status_code == 200
    assert upd.json()["name"] == "宏观与金融研判"

    assert auth_client.delete(f"/api/prompts/{new_id}").status_code == 200
    assert auth_client.delete(f"/api/prompts/{new_id}").status_code == 404


def test_chat_sse_stream_picker_context_and_save_report(auth_client: TestClient) -> None:
    auth_client.post(
        "/api/ai-providers",
        json={
            "name": "Chat Test Gemini",
            "protocol": "gemini",
            "api_key": "AIza-chat-stub",
            "model": "gemini-2.5-flash",
            "role_bindings": ["chat_default", "summary_report"],
            "is_enabled": True,
        },
    )
    auth_client.app.state.gateway_service._adapter_factory = lambda s, k: _FakeChatGateway()

    sess_resp = auth_client.post("/api/chat/sessions", json={"title": "新对话"})
    assert sess_resp.status_code == 200
    session_id = sess_resp.json()["id"]

    # Missing session returns 404 even on stream endpoint
    assert (
        auth_client.post(
            "/api/chat/sessions/99999/stream",
            json={"content": "hello", "context_items": []},
        ).status_code
        == 404
    )

    with auth_client.stream(
        "POST",
        f"/api/chat/sessions/{session_id}/stream",
        json={
            "content": "分析这两条芯片消息的关联",
            "context_items": [
                {
                    "kind": "news",
                    "id": 101,
                    "title": "AI 芯片算力新基准",
                    "platform_or_domain": "Hacker News",
                    "url": "https://news.ycombinator.com/item?id=1",
                    "metric_label": "热度 85.0",
                }
            ],
        },
    ) as stream_resp:
        assert stream_resp.status_code == 200
        assert stream_resp.headers.get("x-accel-buffering") == "no"
        assert "no-cache" in stream_resp.headers.get("cache-control", "")
        raw_body = "".join(stream_resp.iter_text())

    assert "event: init" in raw_body
    assert "conv-chat-777" in raw_body
    assert "event: delta" in raw_body
    assert "AI 芯片引发广泛关注。" in raw_body
    assert "event: done" in raw_body

    # Verify history & external_conversation_id persistence
    hist = auth_client.get(f"/api/chat/sessions/{session_id}/messages").json()
    assert hist["session"]["external_conversation_id"] == "conv-chat-777"
    assert len(hist["messages"]) == 2
    assert hist["messages"][0]["context_items"][0]["id"] == 101
    assert hist["messages"][1]["content"] == "第一段分析：AI 芯片引发广泛关注。"

    # Save chat directly into reports table
    saved_rep = auth_client.post(
        f"/api/chat/sessions/{session_id}/save-report",
        json={
            "title": "芯片算力对话沉淀报告",
            "domain": "AI大模型",
            "auto_summarize": True,
        },
    )
    assert saved_rep.status_code == 200
    rep = saved_rep.json()
    assert rep["report_type"] == "chat_generated"
    assert rep["source_session_id"] == session_id
    assert rep["related_news_ids"] == [101]
    assert "对话提炼分析报告" in rep["content_md"]

    # Confirm report is retrievable from /api/reports
    listed = auth_client.get("/api/reports", params={"report_type": "chat_generated"}).json()
    assert listed["total"] == 1
    assert listed["items"][0]["title"] == "芯片算力对话沉淀报告"

    # Cleanup session
    assert auth_client.delete(f"/api/chat/sessions/{session_id}").status_code == 200
    assert auth_client.get(f"/api/chat/sessions/{session_id}/messages").status_code == 404