"""AI provider slot management, draft probing, model discovery, and runtime gateway resolution."""

from datetime import datetime
import time
from typing import Any, Callable, Dict, List, Optional, Tuple
import zoneinfo

from app.config import Settings
from app.models import (
    AIProviderCreateRequest,
    AIProviderModelsResponse,
    AIProviderProbeRequest,
    AIProviderRole,
    AIProviderSlotDTO,
    AIProviderTestResponse,
    AIProviderUpdateRequest,
)
from app.repositories.chat_repo import ChatRepository
from app.security import SecretCipher
from app.services.ai_gateway.anthropic_adapter import AnthropicAdapter
from app.services.ai_gateway.base import LLMConfigError, LLMGateway, LLMGatewayError
from app.services.ai_gateway.gemini_adapter import GeminiAdapter
from app.services.ai_gateway.openai_adapter import OpenAIAdapter

_ALL_ROLES: List[AIProviderRole] = ["chat_default", "summary_report", "event_cluster"]


class ProviderNotFoundError(Exception):
    """Raised when a requested AI provider slot ID does not exist."""


class ProviderConflictError(Exception):
    """Raised when a provider slot name duplicates an existing slot."""


def _is_masked_secret(candidate: str) -> bool:
    return bool(candidate) and (set(candidate) == {"*"} or "***" in candidate)


class AIGatewayService:
    """Service coordinating encrypted AI provider configurations, probing, and gateway instances."""

    def __init__(
        self,
        chat_repo: ChatRepository,
        cipher: SecretCipher,
        settings: Settings,
        adapter_factory: Optional[Callable[[Dict[str, Any], str], LLMGateway]] = None,
    ) -> None:
        """Initialize the AI gateway service.

        Args:
            chat_repo: Repository owning `ai_providers` storage.
            cipher: Symmetric Fernet cipher protecting provider API keys.
            settings: Application settings supplying `agy` binary/proxy/concurrency config.
            adapter_factory: Optional test double `(slot_row, decrypted_key) -> LLMGateway`.
        """
        self._repo = chat_repo
        self._cipher = cipher
        self._settings = settings
        self._tz = zoneinfo.ZoneInfo(settings.timezone)
        self._adapter_factory = adapter_factory

    def _now_iso(self) -> str:
        return datetime.now(self._tz).isoformat(timespec="seconds")

    def _to_dto(self, row: Dict[str, Any]) -> AIProviderSlotDTO:
        enc = str(row.get("api_key_encrypted") or "")
        plaintext = self._cipher.decrypt(enc) if enc else ""
        return AIProviderSlotDTO(
            id=int(row["id"]),
            name=str(row["name"]),
            protocol=row["protocol"],
            base_url=str(row.get("base_url") or ""),
            has_api_key=bool(plaintext),
            api_key_masked=self._cipher.mask_secret(plaintext),
            model=str(row["model"]),
            extra_params=dict(row.get("extra_params") or {}),
            role_bindings=list(row.get("role_bindings") or []),
            is_enabled=bool(row.get("is_enabled", True)),
        )

    def list_slots(self) -> List[AIProviderSlotDTO]:
        """Return all configured AI provider slots with masked credentials.

        Returns:
            List[AIProviderSlotDTO]: Provider slots sorted by ID.
        """
        return [self._to_dto(row) for row in self._repo.list_ai_providers()]

    def create_slot(self, req: AIProviderCreateRequest) -> AIProviderSlotDTO:
        """Create and persist a new encrypted AI provider configuration.

        Args:
            req: Validated creation payload.

        Returns:
            AIProviderSlotDTO: Newly created masked slot DTO.

        Raises:
            ProviderConflictError: If `req.name` already exists.
        """
        name = req.name.strip()
        if self._repo.get_ai_provider_by_name(name) is not None:
            raise ProviderConflictError(f"AI provider '{name}' already exists")

        raw_key = req.api_key.strip()
        enc_key = self._cipher.encrypt(raw_key) if raw_key else ""
        row = self._repo.create_ai_provider(
            name=name,
            protocol=req.protocol,
            base_url=req.base_url.strip(),
            api_key_encrypted=enc_key,
            model=req.model.strip(),
            extra_params=req.extra_params,
            role_bindings=list(dict.fromkeys(req.role_bindings)),
            is_enabled=req.is_enabled,
            now_iso=self._now_iso(),
        )
        return self._to_dto(row)

    def update_slot(self, slot_id: int, req: AIProviderUpdateRequest) -> AIProviderSlotDTO:
        """Update an existing AI provider configuration while preserving masked secrets unless changed.

        Args:
            slot_id: Target slot primary key.
            req: Partial update payload.

        Returns:
            AIProviderSlotDTO: Updated masked slot DTO.

        Raises:
            ProviderNotFoundError: If `slot_id` does not exist.
            ProviderConflictError: If the renamed slot collides with another slot.
        """
        existing = self._repo.get_ai_provider(slot_id)
        if existing is None:
            raise ProviderNotFoundError(f"AI provider {slot_id} not found")

        new_name = req.name.strip() if req.name is not None else str(existing["name"])
        collision = self._repo.get_ai_provider_by_name(new_name)
        if collision is not None and int(collision["id"]) != slot_id:
            raise ProviderConflictError(f"AI provider '{new_name}' already exists")

        enc_key = str(existing.get("api_key_encrypted") or "")
        if req.clear_api_key:
            enc_key = ""
        elif req.api_key is not None and not _is_masked_secret(req.api_key.strip()):
            raw = req.api_key.strip()
            if raw:
                enc_key = self._cipher.encrypt(raw)

        roles = (
            list(dict.fromkeys(req.role_bindings))
            if req.role_bindings is not None
            else list(existing.get("role_bindings") or [])
        )
        updated = self._repo.update_ai_provider(
            slot_id,
            name=new_name,
            protocol=req.protocol or existing["protocol"],
            base_url=req.base_url.strip() if req.base_url is not None else str(existing.get("base_url") or ""),
            api_key_encrypted=enc_key,
            model=req.model.strip() if req.model is not None else str(existing["model"]),
            extra_params=req.extra_params if req.extra_params is not None else dict(existing.get("extra_params") or {}),
            role_bindings=roles,
            is_enabled=req.is_enabled if req.is_enabled is not None else bool(existing["is_enabled"]),
            now_iso=self._now_iso(),
        )
        if updated is None:
            raise ProviderNotFoundError(f"AI provider {slot_id} not found")
        return self._to_dto(updated)

    def activate_slot(self, slot_id: int) -> AIProviderSlotDTO:
        """Promote one saved provider as the active AI across chat, summary reports, and clustering.

        Args:
            slot_id: Target provider primary key.

        Returns:
            AIProviderSlotDTO: Updated active provider DTO.

        Raises:
            ProviderNotFoundError: If `slot_id` does not exist.
        """
        existing = self._repo.get_ai_provider(slot_id)
        if existing is None:
            raise ProviderNotFoundError(f"AI provider {slot_id} not found")
        updated = self._repo.update_ai_provider(
            slot_id,
            name=str(existing["name"]),
            protocol=str(existing["protocol"]),
            base_url=str(existing.get("base_url") or ""),
            api_key_encrypted=str(existing.get("api_key_encrypted") or ""),
            model=str(existing["model"]),
            extra_params=dict(existing.get("extra_params") or {}),
            role_bindings=list(_ALL_ROLES),
            is_enabled=True,
            now_iso=self._now_iso(),
        )
        if updated is None:
            raise ProviderNotFoundError(f"AI provider {slot_id} not found")
        return self._to_dto(updated)

    def delete_slot(self, slot_id: int) -> None:
        """Delete an AI provider configuration.

        Args:
            slot_id: Slot primary key.

        Raises:
            ProviderNotFoundError: If slot does not exist.
        """
        if not self._repo.delete_ai_provider(slot_id):
            raise ProviderNotFoundError(f"AI provider {slot_id} not found")

    def _build_adapter_from_values(
        self,
        *,
        slot_row: Dict[str, Any],
        protocol: str,
        base_url: str,
        api_key: str,
    ) -> LLMGateway:
        if self._adapter_factory is not None:
            return self._adapter_factory(slot_row, api_key)

        if protocol == "openai":
            return OpenAIAdapter(api_key=api_key, base_url=base_url)
        if protocol == "anthropic":
            return AnthropicAdapter(api_key=api_key, base_url=base_url)
        if protocol == "gemini":
            return GeminiAdapter(api_key=api_key, base_url=base_url)
        raise LLMConfigError(f"Unsupported AI protocol: {protocol}")

    def build_adapter(self, slot_row: Dict[str, Any]) -> LLMGateway:
        """Construct the concrete `LLMGateway` adapter for a persisted slot record.

        Args:
            slot_row: Raw database record from `ai_providers`.

        Returns:
            LLMGateway: Initialized protocol adapter.

        Raises:
            LLMConfigError: When `protocol` is unrecognized.
        """
        enc = str(slot_row.get("api_key_encrypted") or "")
        api_key = self._cipher.decrypt(enc) if enc else ""
        return self._build_adapter_from_values(
            slot_row=slot_row,
            protocol=str(slot_row["protocol"]),
            base_url=str(slot_row.get("base_url") or ""),
            api_key=api_key,
        )

    def _resolve_probe_adapter(self, req: AIProviderProbeRequest) -> LLMGateway:
        raw_key = req.api_key.strip()
        if (not raw_key or _is_masked_secret(raw_key)) and req.slot_id is not None:
            stored = self._repo.get_ai_provider(req.slot_id)
            if stored is not None and stored.get("api_key_encrypted"):
                raw_key = self._cipher.decrypt(str(stored["api_key_encrypted"]))
        if _is_masked_secret(raw_key):
            raw_key = ""

        pseudo_row: Dict[str, Any] = {
            "id": req.slot_id or 0,
            "name": "probe",
            "protocol": req.protocol,
            "base_url": req.base_url.strip(),
            "model": req.model.strip(),
            "extra_params": req.extra_params,
        }
        return self._build_adapter_from_values(
            slot_row=pseudo_row,
            protocol=req.protocol,
            base_url=req.base_url.strip(),
            api_key=raw_key,
        )

    def find_slot_by_role(self, role: str) -> Optional[Dict[str, Any]]:
        """Find the first enabled slot bound to a given role if present.

        Args:
            role: Role identifier (`chat_default`, `summary_report`, `event_cluster`).

        Returns:
            Optional[Dict[str, Any]]: Raw slot dict or None.
        """
        for row in self._repo.list_ai_providers():
            if row["is_enabled"] and role in (row.get("role_bindings") or []):
                return row
        return None

    def resolve_slot(
        self,
        *,
        slot_id: Optional[int] = None,
        role: Optional[str] = None,
        fallback_any: bool = False,
    ) -> Tuple[Dict[str, Any], LLMGateway]:
        """Resolve an active provider slot and construct its gateway adapter.

        Args:
            slot_id: Explicit slot override ID.
            role: Functional role used when `slot_id` is omitted.
            fallback_any: Whether to fall back to the first enabled slot when role is unbound.

        Returns:
            Tuple[Dict[str, Any], LLMGateway]: `(slot_row, adapter)`.

        Raises:
            LLMConfigError: If no matching enabled provider slot is available.
        """
        selected: Optional[Dict[str, Any]] = None
        if slot_id is not None:
            candidate = self._repo.get_ai_provider(slot_id)
            if candidate is None:
                raise LLMConfigError(f"AI provider {slot_id} does not exist")
            if not candidate["is_enabled"]:
                raise LLMConfigError(f"AI provider '{candidate['name']}' is disabled")
            selected = candidate
        else:
            if role:
                selected = self.find_slot_by_role(role)
            if selected is None and fallback_any:
                selected = next((r for r in self._repo.list_ai_providers() if r["is_enabled"]), None)

        if selected is None:
            raise LLMConfigError("No enabled AI provider is configured for this operation")
        return selected, self.build_adapter(selected)

    async def list_models_for_config(self, req: AIProviderProbeRequest) -> AIProviderModelsResponse:
        """Discover selectable models from an unsaved or existing AI configuration.

        Args:
            req: Provider protocol, URL, optional token, and optional saved `slot_id`.

        Returns:
            AIProviderModelsResponse: Discovered model IDs and summary note.

        Raises:
            LLMGatewayError: When authentication fails or upstream endpoint errors.
        """
        adapter = self._resolve_probe_adapter(req)
        models = await adapter.list_models(req.extra_params)
        return AIProviderModelsResponse(
            models=models,
            message=f"已获取 {len(models)} 个可用模型" if models else "站点连通正常，但未返回模型列表，请手动填写模型 ID",
        )

    async def test_config(self, req: AIProviderProbeRequest) -> AIProviderTestResponse:
        """Test live connectivity against an unsaved form configuration or existing slot.

        Args:
            req: Probe payload with URL, token, protocol, and optional model.

        Returns:
            AIProviderTestResponse: Connectivity result and latency in milliseconds.
        """
        started = time.monotonic()
        target_model = req.model.strip()
        try:
            adapter = self._resolve_probe_adapter(req)
            if target_model:
                parsed, _ = await adapter.complete_json(
                    messages=[{"role": "user", "content": 'Reply strictly with JSON: {"ok": true}'}],
                    model=target_model,
                    system_prompt="You are a health check probe. Return valid JSON only.",
                    extra_params=dict(req.extra_params or {}),
                )
                ok = bool(parsed)
                msg = "connected"
            else:
                models = await adapter.list_models(req.extra_params)
                ok = True
                msg = f"connected ({len(models)} models found)"
            elapsed_ms = int((time.monotonic() - started) * 1000)
            return AIProviderTestResponse(
                ok=ok,
                latency_ms=elapsed_ms,
                message=msg,
                model=target_model or "(auto)",
            )
        except LLMGatewayError as exc:
            elapsed_ms = int((time.monotonic() - started) * 1000)
            return AIProviderTestResponse(
                ok=False,
                latency_ms=elapsed_ms,
                message=exc.message,
                model=target_model or "(auto)",
            )
        except Exception as exc:
            elapsed_ms = int((time.monotonic() - started) * 1000)
            return AIProviderTestResponse(
                ok=False,
                latency_ms=elapsed_ms,
                message=str(exc),
                model=target_model or "(auto)",
            )

    async def test_slot(self, slot_id: int) -> AIProviderTestResponse:
        """Execute a lightweight connectivity probe against a saved AI provider slot.

        Args:
            slot_id: Target provider slot ID.

        Returns:
            AIProviderTestResponse: Latency, connectivity boolean, and diagnostic message.

        Raises:
            ProviderNotFoundError: If slot ID is unknown.
        """
        slot = self._repo.get_ai_provider(slot_id)
        if slot is None:
            raise ProviderNotFoundError(f"AI provider {slot_id} not found")
        return await self.test_config(
            AIProviderProbeRequest(
                protocol=slot["protocol"],
                base_url=str(slot.get("base_url") or ""),
                model=str(slot["model"]),
                extra_params=dict(slot.get("extra_params") or {}),
                slot_id=slot_id,
            )
        )
