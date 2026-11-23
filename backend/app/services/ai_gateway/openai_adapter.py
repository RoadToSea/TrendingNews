"""OpenAI-compatible asynchronous LLM gateway adapter supporting custom relays."""

from typing import Any, AsyncIterator, Dict, List, Optional, Tuple
from urllib.parse import urlparse

import openai

from app.services.ai_gateway.base import (
    LLMConfigError,
    LLMRateLimitError,
    LLMTimeoutError,
    LLMUpstreamError,
    StreamEvent,
    extract_json_object,
)


def _split_client_kwargs(extra_params: Optional[Dict[str, Any]]) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    params = dict(extra_params or {})
    default_headers = params.pop("extra_headers", None)
    if not isinstance(default_headers, dict):
        default_headers = None

    request_kwargs: Dict[str, Any] = {}
    for key in ("temperature", "max_tokens", "top_p", "presence_penalty", "frequency_penalty", "extra_body"):
        if key in params and params[key] is not None:
            request_kwargs[key] = params[key]
    return {"default_headers": default_headers}, request_kwargs


class OpenAIAdapter:
    """`LLMGateway` adapter backed by `openai.AsyncOpenAI`."""

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str = "",
        timeout_sec: int = 120,
        client_factory: Any = None,
    ) -> None:
        """Initialize the OpenAI-compatible adapter.

        Args:
            api_key: Decrypted API key (optional only when a custom local `base_url` is set).
            base_url: Optional custom endpoint URL (e.g. third-party relay or local gateway).
            timeout_sec: Request timeout in seconds.
            client_factory: Optional test double factory returning an `AsyncOpenAI`-like client.
        """
        self._api_key = api_key.strip()
        self._base_url = base_url.strip()
        self._timeout_sec = timeout_sec
        self._client_factory = client_factory

    def _build_client(self, extra_params: Optional[Dict[str, Any]]) -> Tuple[Any, Dict[str, Any]]:
        if not self._api_key:
            host = (urlparse(self._base_url).hostname or "").lower()
            if not self._base_url or host in ("api.openai.com", "openai.com"):
                raise LLMConfigError("请先填写访问令牌 (API Key)")

        client_opts, req_kwargs = _split_client_kwargs(extra_params)
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
        return openai.AsyncOpenAI(**kwargs), req_kwargs

    @staticmethod
    def _build_messages(messages: List[Dict[str, str]], system_prompt: str) -> List[Dict[str, str]]:
        payload: List[Dict[str, str]] = []
        if system_prompt.strip():
            payload.append({"role": "system", "content": system_prompt.strip()})
        for msg in messages:
            role = msg.get("role", "user")
            content = str(msg.get("content", ""))
            if content:
                payload.append({"role": role, "content": content})
        return payload

    @staticmethod
    async def _close_client(client: Any) -> None:
        close_fn = getattr(client, "close", None)
        if callable(close_fn):
            await close_fn()

    @staticmethod
    def _map_exception(exc: Exception) -> LLMUpstreamError | LLMTimeoutError | LLMRateLimitError:
        if isinstance(exc, openai.APITimeoutError):
            return LLMTimeoutError(f"OpenAI request timed out: {exc}")
        if isinstance(exc, openai.RateLimitError):
            return LLMRateLimitError(f"OpenAI rate limited: {exc}")
        return LLMUpstreamError(f"OpenAI request failed: {exc}")

    async def stream_chat(
        self,
        messages: List[Dict[str, str]],
        model: str,
        *,
        system_prompt: str = "",
        external_conversation_id: str = "",
        extra_params: Optional[Dict[str, Any]] = None,
    ) -> AsyncIterator[StreamEvent]:
        """Stream chat tokens from an OpenAI-compatible chat completions endpoint.

        Args:
            messages: Conversation turns `[{"role": ..., "content": ...}]`.
            model: Target model identifier.
            system_prompt: Optional system instruction.
            external_conversation_id: Unused for stateless OpenAI protocol; preserved in event.
            extra_params: Optional model parameters (`temperature`, `extra_headers`, `extra_body`, etc.).

        Yields:
            StreamEvent: `init`, `delta`, and `done` events.

        Raises:
            LLMConfigError: When credentials are missing.
            LLMTimeoutError: When the request times out.
            LLMRateLimitError: When rate limited (`429`).
            LLMUpstreamError: On upstream API errors.
        """
        client, req_kwargs = self._build_client(extra_params)
        payload = self._build_messages(messages, system_prompt)
        yield StreamEvent(type="init", conversation_id=external_conversation_id)

        usage: Dict[str, Any] = {}
        try:
            stream = await client.chat.completions.create(
                model=model,
                messages=payload,
                stream=True,
                **req_kwargs,
            )
            async for chunk in stream:
                chunk_usage = getattr(chunk, "usage", None)
                if chunk_usage is not None and hasattr(chunk_usage, "model_dump"):
                    usage = chunk_usage.model_dump()
                choices = getattr(chunk, "choices", None) or []
                if not choices:
                    continue
                delta_obj = getattr(choices[0], "delta", None)
                if delta_obj is None:
                    continue
                text = getattr(delta_obj, "content", None) or ""
                if text:
                    yield StreamEvent(type="delta", text=text)
            yield StreamEvent(type="done", conversation_id=external_conversation_id, usage=usage)
        except openai.APIError as exc:
            raise self._map_exception(exc) from exc
        except Exception as exc:
            if isinstance(exc, LLMUpstreamError | LLMTimeoutError | LLMRateLimitError | LLMConfigError):
                raise
            raise LLMUpstreamError(f"OpenAI request failed: {exc}") from exc
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
        """Execute a JSON completion request, falling back cleanly if `response_format` is unsupported.

        Args:
            messages: Conversation turns.
            model: Model identifier.
            system_prompt: Optional system prompt.
            extra_params: Optional model parameters.

        Returns:
            Tuple[Dict[str, Any], Dict[str, Any]]: `(parsed_json, usage_dict)`.

        Raises:
            LLMConfigError: When credentials are missing.
            LLMTimeoutError: On timeout.
            LLMRateLimitError: On HTTP 429.
            LLMUpstreamError: On API error or invalid JSON output.
        """
        client, req_kwargs = self._build_client(extra_params)
        payload = self._build_messages(messages, system_prompt)
        try:
            try:
                resp = await client.chat.completions.create(
                    model=model,
                    messages=payload,
                    response_format={"type": "json_object"},
                    **req_kwargs,
                )
            except openai.BadRequestError:
                # Some third-party relays reject response_format; retry with prompt instructions only.
                resp = await client.chat.completions.create(
                    model=model,
                    messages=payload,
                    **req_kwargs,
                )
        except Exception as exc:
            raise self._map_exception(exc) from exc
        finally:
            await self._close_client(client)

        content = ""
        if resp.choices:
            content = resp.choices[0].message.content or ""
        usage = resp.usage.model_dump() if getattr(resp, "usage", None) else {}
        return extract_json_object(content), usage

    async def list_models(self, extra_params: Optional[Dict[str, Any]] = None) -> List[str]:
        """Fetch selectable model IDs via the OpenAI `/models` endpoint.

        Args:
            extra_params: Optional parameters containing `extra_headers`.

        Returns:
            List[str]: Sorted distinct model identifiers.

        Raises:
            LLMGatewayError: When credentials are invalid or the endpoint fails.
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