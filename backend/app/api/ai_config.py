"""AI provider configuration, probing, model discovery, and prompt template endpoints."""

from typing import List

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.deps import get_chat_service, get_current_user, get_gateway_service, require_admin
from app.models import (
    AIProviderCreateRequest,
    AIProviderModelsResponse,
    AIProviderProbeRequest,
    AIProviderSlotDTO,
    AIProviderTestResponse,
    AIProviderUpdateRequest,
    PromptTemplateCreateRequest,
    PromptTemplateDTO,
    PromptTemplateUpdateRequest,
)
from app.repositories.user_repo import UserRecord
from app.services.ai_gateway.base import LLMGatewayError
from app.services.ai_gateway.gateway_service import (
    AIGatewayService,
    ProviderConflictError,
    ProviderNotFoundError,
)
from app.services.chat_service import ChatNotFoundError, ChatService, PromptConflictError

router = APIRouter(prefix="/api", tags=["ai-config"])


@router.get("/ai-providers", response_model=List[AIProviderSlotDTO])
def list_ai_providers(
    _: UserRecord = Depends(require_admin),
    gateway: AIGatewayService = Depends(get_gateway_service),
) -> List[AIProviderSlotDTO]:
    """List all saved AI provider configurations with masked API keys."""
    return gateway.list_slots()


@router.post("/ai-providers", response_model=AIProviderSlotDTO)
def create_ai_provider(
    body: AIProviderCreateRequest,
    _: UserRecord = Depends(require_admin),
    gateway: AIGatewayService = Depends(get_gateway_service),
) -> AIProviderSlotDTO:
    """Create a new AI provider configuration with encrypted API credentials."""
    try:
        return gateway.create_slot(body)
    except ProviderConflictError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.post("/ai-providers/test", response_model=AIProviderTestResponse)
async def test_draft_ai_provider(
    body: AIProviderProbeRequest,
    _: UserRecord = Depends(require_admin),
    gateway: AIGatewayService = Depends(get_gateway_service),
) -> AIProviderTestResponse:
    """Test connectivity for an unsaved AI form configuration (URL + Token + optional model)."""
    return await gateway.test_config(body)


@router.post("/ai-providers/models", response_model=AIProviderModelsResponse)
async def fetch_ai_provider_models(
    body: AIProviderProbeRequest,
    _: UserRecord = Depends(require_admin),
    gateway: AIGatewayService = Depends(get_gateway_service),
) -> AIProviderModelsResponse:
    """Fetch available models exposed by the given AI endpoint and token."""
    try:
        return await gateway.list_models_for_config(body)
    except LLMGatewayError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc


@router.put("/ai-providers/{slot_id}", response_model=AIProviderSlotDTO)
def update_ai_provider(
    slot_id: int,
    body: AIProviderUpdateRequest,
    _: UserRecord = Depends(require_admin),
    gateway: AIGatewayService = Depends(get_gateway_service),
) -> AIProviderSlotDTO:
    """Update a saved AI provider configuration."""
    try:
        return gateway.update_slot(slot_id, body)
    except ProviderNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ProviderConflictError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.post("/ai-providers/{slot_id}/activate", response_model=AIProviderSlotDTO)
def activate_ai_provider(
    slot_id: int,
    _: UserRecord = Depends(require_admin),
    gateway: AIGatewayService = Depends(get_gateway_service),
) -> AIProviderSlotDTO:
    """Set a saved AI provider as the current active model across chat, reports, and clustering."""
    try:
        return gateway.activate_slot(slot_id)
    except ProviderNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.delete("/ai-providers/{slot_id}")
def delete_ai_provider(
    slot_id: int,
    _: UserRecord = Depends(require_admin),
    gateway: AIGatewayService = Depends(get_gateway_service),
) -> dict:
    """Delete an AI provider configuration."""
    try:
        gateway.delete_slot(slot_id)
    except ProviderNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return {"ok": True}


@router.post("/ai-providers/{slot_id}/test", response_model=AIProviderTestResponse)
async def test_ai_provider(
    slot_id: int,
    _: UserRecord = Depends(require_admin),
    gateway: AIGatewayService = Depends(get_gateway_service),
) -> AIProviderTestResponse:
    """Run a live connectivity test against a saved AI provider configuration."""
    try:
        return await gateway.test_slot(slot_id)
    except ProviderNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.get("/prompts", response_model=List[PromptTemplateDTO])
def list_prompts(
    _: UserRecord = Depends(get_current_user),
    chat_service: ChatService = Depends(get_chat_service),
) -> List[PromptTemplateDTO]:
    """List all configured chat opening system prompt templates."""
    return chat_service.list_prompts()


@router.post("/prompts", response_model=PromptTemplateDTO)
def create_prompt(
    body: PromptTemplateCreateRequest,
    _: UserRecord = Depends(get_current_user),
    chat_service: ChatService = Depends(get_chat_service),
) -> PromptTemplateDTO:
    """Create a new chat opening system prompt template."""
    try:
        return chat_service.create_prompt(body)
    except PromptConflictError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.put("/prompts/{template_id}", response_model=PromptTemplateDTO)
def update_prompt(
    template_id: int,
    body: PromptTemplateUpdateRequest,
    _: UserRecord = Depends(get_current_user),
    chat_service: ChatService = Depends(get_chat_service),
) -> PromptTemplateDTO:
    """Update a chat opening system prompt template."""
    try:
        return chat_service.update_prompt(template_id, body)
    except ChatNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except PromptConflictError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.delete("/prompts/{template_id}")
def delete_prompt(
    template_id: int,
    _: UserRecord = Depends(get_current_user),
    chat_service: ChatService = Depends(get_chat_service),
) -> dict:
    """Delete a prompt template by ID."""
    try:
        chat_service.delete_prompt(template_id)
    except ChatNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return {"ok": True}
