"""Tests for AI provider CRUD, encrypted keys, RBAC, DB migration, and Gemini/OpenAI/Anthropic adapters."""

import json
from pathlib import Path
import sqlite3
from types import SimpleNamespace

from fastapi.testclient import TestClient
import httpx
import pytest

from app.repositories.db import Database
from app.services.ai_gateway.anthropic_adapter import AnthropicAdapter
from app.services.ai_gateway.base import LLMConfigError, LLMRateLimitError
from app.services.ai_gateway.gemini_adapter import GeminiAdapter
from app.services.ai_gateway.openai_adapter import OpenAIAdapter


def test_ai_provider_crud_masking_and_exclusive_role_switch(auth_client: TestClient) -> None:
    initial = auth_client.get("/api/ai-providers").json()
    assert initial == []

    first_resp = auth_client.post(
        "/api/ai-providers",
        json={
            "name": "Google AI Studio",
            "protocol": "gemini",
            "base_url": "https://generativelanguage.googleapis.com/v1beta",
            "api_key": "AIza-secret-gemini-1122",
            "model": "gemini-2.5-flash",
            "role_bindings": ["chat_default", "summary_report", "event_cluster"],
            "is_enabled": True,
        },
    )
    assert first_resp.status_code == 200
    first_id = first_resp.json()["id"]
    assert first_resp.json()["protocol"] == "gemini"

    create_resp = auth_client.post(
        "/api/ai-providers",
        json={
            "name": "中转 GPT-4o",
            "protocol": "openai",
            "base_url": "https://relay.example.com/v1",
            "api_key": "sk-secret-openai-998877",
            "model": "gpt-4o-mini",
            "extra_params": {"temperature": 0.3},
            "role_bindings": ["chat_default", "summary_report"],
            "is_enabled": True,
        },
    )
    assert create_resp.status_code == 200
    created = create_resp.json()
    assert created["has_api_key"] is True
    assert "998877" not in created["api_key_masked"]
    assert "***" in created["api_key_masked"]

    dup = auth_client.post(
        "/api/ai-providers",
        json={"name": "中转 GPT-4o", "protocol": "openai", "model": "gpt-4o"},
    )
    assert dup.status_code == 409

    # Role binding 'chat_default' must have been stripped from the first slot (exclusive role switch)
    all_slots = auth_client.get("/api/ai-providers").json()
    first_after = next(s for s in all_slots if s["id"] == first_id)
    assert "chat_default" not in first_after["role_bindings"]

    # Updating slot while sending masked key preserves encrypted secret
    upd = auth_client.put(
        f"/api/ai-providers/{created['id']}",
        json={
            "model": "gpt-4.1-mini",
            "api_key": created["api_key_masked"],
        },
    )
    assert upd.status_code == 200
    assert upd.json()["model"] == "gpt-4.1-mini"
    stored_row = auth_client.app.state.chat_repo.get_ai_provider(created["id"])
    assert (
        auth_client.app.state.settings_service._cipher.decrypt(stored_row["api_key_encrypted"])
        == "sk-secret-openai-998877"
    )

    class _ProbeAdapter:
        def __init__(self, key: str):
            self.key = key

        async def complete_json(self, messages, model, **kwargs):
            return {"ok": True}, {"total_tokens": 5}

        async def list_models(self, extra_params=None):
            assert self.key == "sk-secret-openai-998877"
            return ["gpt-4.1-mini", "gpt-4o"]

    auth_client.app.state.gateway_service._adapter_factory = lambda slot, key: _ProbeAdapter(key)
    test_resp = auth_client.post(f"/api/ai-providers/{created['id']}/test")
    assert test_resp.status_code == 200
    assert test_resp.json()["ok"] is True

    draft_models = auth_client.post(
        "/api/ai-providers/models",
        json={
            "protocol": "openai",
            "base_url": "https://relay.example.com/v1",
            "api_key": created["api_key_masked"],
            "slot_id": created["id"],
        },
    )
    assert draft_models.status_code == 200
    assert draft_models.json()["models"] == ["gpt-4.1-mini", "gpt-4o"]

    draft_test = auth_client.post(
        "/api/ai-providers/test",
        json={
            "protocol": "openai",
            "base_url": "https://relay.example.com/v1",
            "api_key": "",
            "model": "",
            "slot_id": created["id"],
        },
    )
    assert draft_test.status_code == 200
    assert draft_test.json()["ok"] is True

    act_resp = auth_client.post(f"/api/ai-providers/{created['id']}/activate")
    assert act_resp.status_code == 200
    assert set(act_resp.json()["role_bindings"]) == {"chat_default", "summary_report", "event_cluster"}

    assert auth_client.delete(f"/api/ai-providers/{created['id']}").status_code == 200
    assert auth_client.delete(f"/api/ai-providers/{first_id}").status_code == 200


@pytest.mark.asyncio
async def test_gemini_adapter_models_json_stream_and_errors() -> None:
    def _handler(request: httpx.Request) -> httpx.Response:
        assert request.headers.get("x-goog-api-key") == "AIza-unit-test"
        url = str(request.url)
        if url.endswith("/models"):
            return httpx.Response(
                200,
                json={
                    "models": [
                        {
                            "name": "models/gemini-2.5-flash",
                            "supportedGenerationMethods": ["generateContent", "countTokens"],
                        },
                        {
                            "name": "models/embedding-001",
                            "supportedGenerationMethods": ["embedContent"],
                        },
                        {
                            "name": "models/gemini-2.5-pro",
                            "supportedGenerationMethods": ["generateContent"],
                        },
                    ]
                },
            )
        if ":generateContent" in url:
            body = json.loads(request.content.decode("utf-8"))
            assert body["systemInstruction"]["parts"][0]["text"] == "sys"
            assert body["generationConfig"]["responseMimeType"] == "application/json"
            return httpx.Response(
                200,
                json={
                    "candidates": [{"content": {"parts": [{"text": '{"ok": true, "count": 2}'}]}}],
                    "usageMetadata": {"totalTokenCount": 42},
                },
            )
        if ":streamGenerateContent" in url:
            sse_body = (
                'data: {"candidates":[{"content":{"parts":[{"text":"第一段"}]}}]}\n\n'
                'data: {"candidates":[{"content":{"parts":[{"text":"第二段"}]}}],"usageMetadata":{"totalTokenCount":25}}\n\n'
            )
            return httpx.Response(200, content=sse_body.encode("utf-8"))
        return httpx.Response(404, json={"error": {"message": "not found"}})

    adapter = GeminiAdapter(
        api_key="AIza-unit-test",
        transport=httpx.MockTransport(_handler),
    )

    models = await adapter.list_models()
    assert models == ["gemini-2.5-flash", "gemini-2.5-pro"]

    parsed, usage = await adapter.complete_json(
        [{"role": "user", "content": "hi"}],
        "gemini-2.5-flash",
        system_prompt="sys",
        extra_params={"temperature": 0.2},
    )
    assert parsed == {"ok": True, "count": 2}
    assert usage["totalTokenCount"] == 42

    events = [
        ev
        async for ev in adapter.stream_chat(
            [{"role": "user", "content": "分析"}, {"role": "assistant", "content": "收到"}],
            "models/gemini-2.5-flash",
            system_prompt="sys",
        )
    ]
    assert events[0].type == "init"
    assert [e.text for e in events if e.type == "delta"] == ["第一段", "第二段"]
    assert events[-1].type == "done"
    assert events[-1].usage["totalTokenCount"] == 25

    rate_limited = GeminiAdapter(
        api_key="AIza-unit-test",
        transport=httpx.MockTransport(
            lambda req: httpx.Response(429, json={"error": {"message": "Quota exceeded"}})
        ),
    )
    with pytest.raises(LLMRateLimitError, match="Quota exceeded"):
        await rate_limited.complete_json([{"role": "user", "content": "hi"}], "gemini-2.5-flash")


@pytest.mark.asyncio
async def test_openai_and_anthropic_adapters_complete_json() -> None:
    class _FakeOpenAIClient:
        class chat:
            class completions:
                @staticmethod
                async def create(**kwargs):
                    return SimpleNamespace(
                        choices=[SimpleNamespace(message=SimpleNamespace(content='```json\n{"events": [1, 2]}\n```'))],
                        usage=SimpleNamespace(model_dump=lambda: {"total_tokens": 11}),
                    )

        async def close(self):
            return None

    oa = OpenAIAdapter(api_key="sk-test", client_factory=lambda: _FakeOpenAIClient())
    parsed, usage = await oa.complete_json([{"role": "user", "content": "hi"}], "gpt-4o-mini")
    assert parsed == {"events": [1, 2]}
    assert usage == {"total_tokens": 11}

    class _FakeAnthropicClient:
        class messages:
            @staticmethod
            async def create(**kwargs):
                assert kwargs.get("system") == "sys"
                return SimpleNamespace(
                    content=[SimpleNamespace(type="text", text='{"status": "ok"}')],
                    usage=SimpleNamespace(model_dump=lambda: {"input_tokens": 4, "output_tokens": 3}),
                )

        async def close(self):
            return None

    ant = AnthropicAdapter(api_key="ant-test", client_factory=lambda: _FakeAnthropicClient())
    parsed_a, usage_a = await ant.complete_json(
        [{"role": "user", "content": "hi"}],
        "claude-sonnet-4-6",
        system_prompt="sys",
    )
    assert parsed_a == {"status": "ok"}
    assert usage_a["output_tokens"] == 3


@pytest.mark.asyncio
async def test_official_hosts_reject_empty_api_key() -> None:
    oa_official = OpenAIAdapter(api_key="", base_url="https://api.openai.com/v1")
    with pytest.raises(LLMConfigError, match="API Key"):
        await oa_official.list_models()

    ant_official = AnthropicAdapter(api_key="", base_url="https://api.anthropic.com")
    with pytest.raises(LLMConfigError, match="API Key"):
        await ant_official.list_models()

    gem_official = GeminiAdapter(api_key="", base_url="")
    with pytest.raises(LLMConfigError, match="API Key"):
        await gem_official.list_models()

    class _FakeLocalClient:
        class models:
            @staticmethod
            async def list():
                return SimpleNamespace(data=[SimpleNamespace(id="qwen2.5:7b")])

        async def close(self):
            return None

    oa_local = OpenAIAdapter(
        api_key="",
        base_url="http://127.0.0.1:11434/v1",
        client_factory=lambda: _FakeLocalClient(),
    )
    assert await oa_local.list_models() == ["qwen2.5:7b"]


def test_legacy_antigravity_table_migrates_to_gemini_constraint(tmp_path: Path) -> None:
    db_path = tmp_path / "legacy_ai.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        """
        CREATE TABLE ai_providers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            protocol TEXT NOT NULL CHECK(protocol IN ('openai', 'anthropic', 'antigravity')),
            base_url TEXT NOT NULL DEFAULT '',
            api_key_encrypted TEXT NOT NULL DEFAULT '',
            model TEXT NOT NULL,
            extra_params_json TEXT NOT NULL DEFAULT '{}',
            role_bindings_json TEXT NOT NULL DEFAULT '[]',
            is_enabled INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        """
    )
    conn.execute(
        """
        CREATE TABLE users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'admin',
            is_active INTEGER NOT NULL DEFAULT 1,
            invited_by_code_id INTEGER DEFAULT NULL,
            last_login_at TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        """
    )
    conn.execute(
        """
        CREATE TABLE chat_sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            title TEXT NOT NULL,
            provider_slot_id INTEGER,
            external_conversation_id TEXT NOT NULL DEFAULT '',
            prompt_template_id INTEGER,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        """
    )
    conn.execute(
        """
        CREATE TABLE reports (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            report_type TEXT NOT NULL,
            report_date TEXT NOT NULL,
            domain TEXT NOT NULL DEFAULT '',
            title TEXT NOT NULL,
            content_md TEXT NOT NULL,
            related_event_ids_json TEXT NOT NULL DEFAULT '[]',
            related_news_ids_json TEXT NOT NULL DEFAULT '[]',
            source_session_id INTEGER,
            provider_slot_id INTEGER,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        """
    )
    conn.execute(
        """
        INSERT INTO ai_providers (name, protocol, model, created_at, updated_at)
        VALUES ('Old Agy', 'antigravity', 'gemini-3.8-flash-medium', '2026-11-22T00:00:00', '2026-11-22T00:00:00')
        """
    )
    conn.execute(
        """
        INSERT INTO ai_providers (name, protocol, model, created_at, updated_at)
        VALUES ('Keep OpenAI', 'openai', 'gpt-4o-mini', '2026-11-22T00:00:00', '2026-11-22T00:00:00')
        """
    )
    conn.execute(
        "INSERT INTO chat_sessions (user_id, title, provider_slot_id, created_at, updated_at) VALUES (1, 'S1', 1, '2026-11-22T00:00:00', '2026-11-22T00:00:00')"
    )
    conn.commit()
    conn.close()

    Database(db_path).init_schema()

    verify = sqlite3.connect(str(db_path))
    rows = verify.execute("SELECT name, protocol FROM ai_providers ORDER BY id").fetchall()
    assert rows == [("Keep OpenAI", "openai")]
    sess_slot = verify.execute("SELECT provider_slot_id FROM chat_sessions WHERE id = 1").fetchone()[0]
    assert sess_slot is None
    verify.execute(
        """
        INSERT INTO ai_providers (name, protocol, model, created_at, updated_at)
        VALUES ('Google Gemini', 'gemini', 'gemini-2.5-flash', '2026-11-28T00:00:00', '2026-11-28T00:00:00')
        """
    )
    verify.commit()
    verify.close()
