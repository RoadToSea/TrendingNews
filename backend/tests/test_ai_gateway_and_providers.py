"""Tests for cc-switch AI provider CRUD, encrypted keys, and Antigravity/OpenAI/Anthropic adapters."""

import asyncio
import json
import os
from pathlib import Path
import sys
from types import SimpleNamespace
from typing import Any, Dict, List

from fastapi.testclient import TestClient
import pytest

from app.services.ai_gateway.anthropic_adapter import AnthropicAdapter
from app.services.ai_gateway.antigravity_adapter import AntigravityCLIAdapter
from app.services.ai_gateway.base import LLMConfigError, LLMRateLimitError
from app.services.ai_gateway.openai_adapter import OpenAIAdapter


def test_ai_provider_crud_masking_and_exclusive_role_switch(auth_client: TestClient) -> None:
    initial = auth_client.get("/api/ai-providers").json()
    assert len(initial) == 1
    default_id = initial[0]["id"]
    assert initial[0]["protocol"] == "antigravity"
    assert set(initial[0]["role_bindings"]) == {"chat_default", "summary_report", "event_cluster"}

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

    # Duplicate name returns 409 Conflict
    dup = auth_client.post(
        "/api/ai-providers",
        json={"name": "中转 GPT-4o", "protocol": "openai", "model": "gpt-4o"},
    )
    assert dup.status_code == 409

    # Role binding 'chat_default' must have been stripped from the Antigravity slot (cc-switch exclusivity)
    all_slots = auth_client.get("/api/ai-providers").json()
    default_after = next(s for s in all_slots if s["id"] == default_id)
    assert "chat_default" not in default_after["role_bindings"]

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

    # Connectivity test & model discovery with injected fake adapter
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


@pytest.mark.asyncio
async def test_antigravity_cli_adapter_ndjson_proxy_cwd_and_continuation(tmp_path: Path) -> None:
    sandbox_dir = tmp_path / "agy-sandbox"
    record_file = tmp_path / "cli_invocation.json"
    fake_cli = tmp_path / "fake_agy.py"
    fake_cli.write_text(
        f"""
import json, os, sys
with open({str(record_file)!r}, "w", encoding="utf-8") as fh:
    json.dump({{
        "argv": sys.argv[1:],
        "cwd": os.getcwd(),
        "http_proxy": os.environ.get("HTTP_PROXY", ""),
        "https_proxy": os.environ.get("HTTPS_PROXY", ""),
    }}, fh)

print(json.dumps({{"event": "init", "conversation_id": "conv-abc-123"}}), flush=True)
print(json.dumps({{
    "event": "step_update",
    "step_update": {{
        "conversation_id": "conv-abc-123",
        "step_index": 1,
        "state": "ACTIVE",
        "step_type": "agent_response",
        "text_delta": "Hello "
    }}
}}), flush=True)
print(json.dumps({{
    "event": "step_update",
    "step_update": {{
        "conversation_id": "conv-abc-123",
        "step_index": 1,
        "state": "DONE",
        "step_type": "agent_response",
        "text_delta": "World"
    }}
}}), flush=True)
print(json.dumps({{
    "event": "result",
    "result": {{
        "conversation_id": "conv-abc-123",
        "status": "SUCCESS",
        "response": "Hello World",
        "usage": {{"output_tokens": 2}}
    }}
}}), flush=True)
""",
        encoding="utf-8",
    )

    adapter = AntigravityCLIAdapter(
        agy_bin=sys.executable,
        proxy_url="http://127.0.0.1:7890",
        workspace=sandbox_dir,
        timeout_sec=30,
        semaphore=asyncio.Semaphore(2),
        extra_args=[str(fake_cli)],
    )

    events = []
    async for ev in adapter.stream_chat(
        [{"role": "user", "content": "Analyze hotlist"}],
        "gemini-3.8-flash-medium",
        system_prompt="Be concise",
    ):
        events.append(ev)

    assert [e.type for e in events] == ["init", "delta", "delta", "done"]
    assert "".join(e.text for e in events if e.type == "delta") == "Hello World"
    assert events[-1].conversation_id == "conv-abc-123"
    assert events[-1].usage == {"output_tokens": 2}

    recorded = json.loads(record_file.read_text(encoding="utf-8"))
    argv: List[str] = recorded["argv"]
    assert Path(recorded["cwd"]).resolve() == sandbox_dir.resolve()
    assert recorded["https_proxy"] == "http://127.0.0.1:7890"
    assert "--dangerously-skip-permissions" not in argv
    assert "--sandbox" in argv
    assert "--disable-slash-commands" in argv
    assert argv[argv.index("--print-timeout") + 1] == "30s"
    assert any(arg.startswith("-p=") for arg in argv)

    # Turn 2 passes --conversation
    events_turn2 = []
    async for ev in adapter.stream_chat(
        [{"role": "user", "content": "Follow up"}],
        "gemini-3.8-flash-medium",
        external_conversation_id="conv-abc-123",
    ):
        events_turn2.append(ev)
    recorded_turn2 = json.loads(record_file.read_text(encoding="utf-8"))
    assert "--conversation" in recorded_turn2["argv"]
    assert "conv-abc-123" in recorded_turn2["argv"]


@pytest.mark.asyncio
async def test_antigravity_concurrency_semaphore_limit(tmp_path: Path) -> None:
    sem = asyncio.Semaphore(1)
    await sem.acquire()
    adapter = AntigravityCLIAdapter(
        agy_bin=sys.executable,
        proxy_url="",
        workspace=tmp_path,
        timeout_sec=10,
        semaphore=sem,
    )
    # Monkeypatch _acquire_slot wait timeout implicitly by checking immediate exhaustion
    with pytest.raises(LLMRateLimitError):
        async def _quick_fail():
            try:
                await asyncio.wait_for(sem.acquire(), timeout=0.05)
            except asyncio.TimeoutError as exc:
                raise LLMRateLimitError("busy") from exc

        adapter._acquire_slot = _quick_fail  # type: ignore[method-assign]
        async for _ in adapter.stream_chat([{"role": "user", "content": "hi"}], "m"):
            pass
    sem.release()


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
async def test_antigravity_list_models_parses_cli_output(tmp_path: Path) -> None:
    fake_cli = tmp_path / "fake_agy_models.py"
    fake_cli.write_text(
        """
import sys
assert sys.argv[1] == "models"
print("Fetching available models...")
print("Available models:")
print("gemini-4-neon-high\\tGemini 4 Neon (High)")
print("gemini-3.8-flash-medium  (default)")
print("claude-sonnet-4-6")
print("gpt-oss-120b-medium")
""",
        encoding="utf-8",
    )
    adapter = AntigravityCLIAdapter(
        agy_bin=sys.executable,
        proxy_url="http://127.0.0.1:7890",
        workspace=tmp_path / "agy-ws",
        timeout_sec=15,
        semaphore=asyncio.Semaphore(2),
        extra_args=[str(fake_cli)],
    )
    models = await adapter.list_models()
    assert models == [
        "gemini-4-neon-high",
        "gemini-3.8-flash-medium",
        "claude-sonnet-4-6",
        "gpt-oss-120b-medium",
    ]


@pytest.mark.asyncio
async def test_official_hosts_reject_empty_api_key() -> None:
    oa_official = OpenAIAdapter(api_key="", base_url="https://api.openai.com/v1")
    with pytest.raises(LLMConfigError, match="API Key"):
        await oa_official.list_models()

    ant_official = AnthropicAdapter(api_key="", base_url="https://api.anthropic.com")
    with pytest.raises(LLMConfigError, match="API Key"):
        await ant_official.list_models()

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