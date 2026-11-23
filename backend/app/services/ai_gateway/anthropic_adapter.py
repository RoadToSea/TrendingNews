"""Anthropic Messages asynchronous LLM gateway adapter supporting custom base URLs."""

from typing import Any, AsyncIterator, Dict, List, Optional, Tuple
from urllib.parse import urlparse

import anthropic

from app.services.ai_gateway.base import (
    LLMConfigError,
    LLMRateLimitError,
    LLMTimeoutError,
    LLMUpstreamError,
    StreamEvent,
    extract_json_object,
)


def _extract_anthropic_params(extra_params: Optional[Dict[str, Any]]) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    params = dict(extra_params or {})
    headers = params.pop("extra_headers", None)
    if not isinstance(headers, dict):
        headers = None
    req_kwargs: Dict[str, Any] = {"max_tokens": int(params.pop("max_tokens", 4096) or 4096)}
    for key in ("temperature", "top_p"):
        if key in params and params[key] is not None:
            req_kwargs[key] = params[key]
    return {"default_headers": headers}, req_kwargs


class AnthropicAdapter:
    """`LLMGateway` adapter backed by `anthropic.AsyncAnthropic`."""

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str = "",
        timeout_sec: int = 120,
        client_factory: Any = None,
    ) -> None:
        """Initialize the Anthropic adapter.

        Args:
            api_key: Decrypted API key.
            base_url: Optional custom Anthropic-compatible proxy URL.
            timeout_sec: Request timeout in seconds.
            client_factory: Optional test double factory.
        """
        self._api_key = api_key.strip()
        self._base_url = base_url.strip()
        self._timeout_sec = timeout_sec
        self._client_factory = client_factory

    def _build_client(self, extra_params: Optional[Dict[str, Any]]) -> Tuple[Any, Dict[str, Any]]:
        if not self._api_key:
            host = (urlparse(self._base_url).hostname or "").lower()
            if not self._base_url or host in ("api.anthropic.com", "anthropic.com"):
                raise LLMConfigError("请先填写访问令牌 (API Key)")

        client_opts, req_kwargs = _extract_anthropic_params(extra_params)
        if self._client_factory is not None:
            return self._client_factory(), req_kwargs

        kwargs: Dict[str, Any] = {
            "api_key": self._api_key or "no-key-needed",
            "timeout": float(self._timeout_sec),
        }
        if self._base_url:
            kwargs["base_url"] = self._base_url
        if client_opts["default_headers"]:
            kwargs["default_headers"] = client_opts["default_headers"]
        return anthropic.AsyncAnthropic(**kwargs), req_kwargs

    @staticmethod
    def _build_messages(messages: List[Dict[str, str]]) -> List[Dict[str, str]]:
        cleaned: List[Dict[str, str]] = []
        for msg in messages:
            role = msg.get("role", "user")
            if role not in ("user", "assistant"):
                role = "user"
            content = str(msg.get("content", ""))
            if content:
                cleaned.append({"role": role, "content": content})
        return cleaned

    @staticmethod
    async def _close_client(client: Any) -> None:
        close_fn = getattr(client, "close", None)
        if callable(close_fn):
            await close_fn()

    @staticmethod
    def _map_exception(exc: Exception) -> LLMUpstreamError | LLMTimeoutError | LLMRateLimitError:
        if isinstance(exc, anthropic.APITimeoutError):
            return LLMTimeoutError(f"Anthropic request timed out: {exc}")
        if isinstance(exc, anthropic.RateLimitError):
            return LLMRateLimitError(f"Anthropic rate limited: {exc}")
        return LLMUpstreamError(f"Anthropic request failed: {exc}")

    async def stream_chat(
        self,
        messages: List[Dict[str, str]],
        model: str,
        *,
        system_prompt: str = "",
        external_conversation_id: str = "",
        extra_params: Optional[Dict[str, Any]] = None,
    ) -> AsyncIterator[StreamEvent]:
        """Stream assistant tokens from an Anthropic Messages endpoint.

        Args:
            messages: Conversation turns.
            model: Target Anthropic model name.
            system_prompt: System prompt passed to `system` field.
            external_conversation_id: Unused for Anthropic protocol; echoed in events.
            extra_params: Optional parameters (`max_tokens`, `temperature`, `extra_headers`, etc.).

        Yields:
            StreamEvent: Normalized `init`, `delta`, and `done` events.

        Raises:
            LLMConfigError: When credentials are missing.
            LLMTimeoutError: On timeout.
            LLMRateLimitError: On HTTP 429.
            LLMUpstreamError: On upstream API failure.
        """
        client, req_kwargs = self._build_client(extra_params)
        payload = self._build_messages(messages)
        yield StreamEvent(type="init", conversation_id=external_conversation_id)

        stream_kwargs: Dict[str, Any] = {
            "model": model,
            "messages": payload,
            **req_kwargs,
        }
        if system_prompt.strip():
            stream_kwargs["system"] = system_prompt.strip()

        usage: Dict[str, Any] = {}
        try:
            async with client.messages.stream(**stream_kwargs) as stream:
                async for text in stream.text_stream:
                    if text:
                        yield StreamEvent(type="delta", text=text)
                final_msg = await stream.get_final_message()
                if getattr(final_msg, "usage", None) is not None and hasattr(final_msg.usage, "model_dump"):
                    usage = final_msg.usage.model_dump()
            yield StreamEvent(type="done", conversation_id=external_conversation_id, usage=usage)
        except Exception as exc:
            if isinstance(exc, LLMUpstreamError | LLMTimeoutError | LLMRateLimitError | LLMConfigError):
                raise
            raise self._map_exception(exc) from exc
        finally:
            await self._close_client(client)

    async def complete_json(
        self,
        messages: List[Dict[str, str]],
        model: str,
        *,
        system_prompt: str = "",
        extra_params: Optional[Dict[str, Any]] = None,
    ) -> Tuple[Dict[str, Any], Dict[str, Any]]:
        """Execute a non-streaming Anthropic Messages call and extract a JSON object.

        Args:
            messages: Conversation turns.
            model: Anthropic model name.
            system_prompt: Optional system prompt.
            extra_params: Optional model parameters.

        Returns:
            Tuple[Dict[str, Any], Dict[str, Any]]: `(parsed_json, usage_dict)`.

        Raises:
            LLMConfigError: When credentials are missing.
            LLMTimeoutError: On timeout.
            LLMRateLimitError: On HTTP 429.
            LLMUpstreamError: On API error or invalid JSON.
        """
        client, req_kwargs = self._build_client(extra_params)
        payload = self._build_messages(messages)
        create_kwargs: Dict[str, Any] = {
            "model": model,
            "messages": payload,
            **req_kwargs,
        }
        if system_prompt.strip():
            create_kwargs["system"] = system_prompt.strip()

        try:
            resp = await client.messages.create(**create_kwargs)
        except Exception as exc:
            raise self._map_exception(exc) from exc
        finally:
            await self._close_client(client)

        text_parts = [getattr(block, "text", "") for block in (resp.content or []) if getattr(block, "type", "") == "text"]
        usage = resp.usage.model_dump() if getattr(resp, "usage", None) else {}
        return extract_json_object("\n".join(text_parts)), usage

    async def list_models(self, extra_params: Optional[Dict[str, Any]] = None) -> List[str]:
        """Fetch selectable model IDs exposed by the Anthropic `/models` endpoint.

        Args:
            extra_params: Optional parameters containing `extra_headers`.

        Returns:
            List[str]: Sorted distinct model identifiers.

        Raises:
            LLMGatewayError: When credentials fail or endpoint does not expose `/models`.
        """
        client, _ = self._build_client(extra_params)
        try:
            page = await client.models.list()
            raw_items = getattr(page, "data", None) or []
            ids = sorted({str(getattr(item, "id", "")).strip() for item in raw_items if getattr(item, "id", None)})
            return [m for m in ids if m]
        except Exception as exc:
            if isinstance(exc, LLMUpstreamError | LLMTimeoutError | LLMRateLimitError | LLMConfigError):
                raise
            raise self._map_exception(exc) from exc
        finally:
            await self._close_client(client)