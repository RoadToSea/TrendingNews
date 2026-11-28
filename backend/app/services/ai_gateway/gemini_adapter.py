"""Google AI Studio (Gemini) REST asynchronous LLM gateway adapter."""

import json
from typing import Any, AsyncIterator, Dict, List, Optional, Tuple
from urllib.parse import urlparse

import httpx

from app.services.ai_gateway.base import (
    LLMConfigError,
    LLMRateLimitError,
    LLMTimeoutError,
    LLMUpstreamError,
    StreamEvent,
    extract_json_object,
)


def _extract_gemini_error(response: httpx.Response) -> str:
    try:
        payload = response.json()
        err = payload.get("error") if isinstance(payload, dict) else None
        if isinstance(err, dict) and err.get("message"):
            return str(err["message"])
    except Exception:
        pass
    return response.text[:200] or f"HTTP {response.status_code}"


def _extract_candidate_text(payload: Dict[str, Any]) -> str:
    candidates = payload.get("candidates") or []
    if not candidates or not isinstance(candidates[0], dict):
        return ""
    content = candidates[0].get("content") or {}
    parts = content.get("parts") or []
    return "".join(str(p.get("text") or "") for p in parts if isinstance(p, dict))


class GeminiAdapter:
    """`LLMGateway` adapter calling Google AI Studio `generativelanguage` REST endpoints."""

    DEFAULT_BASE_URL = "https://generativelanguage.googleapis.com/v1beta"

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str = "",
        timeout_sec: int = 120,
        transport: Optional[httpx.AsyncBaseTransport] = None,
    ) -> None:
        """Initialize the Google AI Studio Gemini adapter.

        Args:
            api_key: Decrypted Google AI Studio API key.
            base_url: Optional custom base URL overriding `DEFAULT_BASE_URL`.
            timeout_sec: Request timeout in seconds.
            transport: Optional `httpx.AsyncBaseTransport` override for unit testing.
        """
        self._api_key = api_key.strip()
        self._base_url = (base_url.strip() or self.DEFAULT_BASE_URL).rstrip("/")
        self._timeout_sec = timeout_sec
        self._transport = transport

    def _validate_credentials(self) -> None:
        if self._api_key:
            return
        host = (urlparse(self._base_url).hostname or "").lower()
        if not host or host == "generativelanguage.googleapis.com":
            raise LLMConfigError("请先填写访问令牌 (API Key)")

    def _build_headers(self, extra_params: Optional[Dict[str, Any]]) -> Dict[str, str]:
        headers: Dict[str, str] = {"Content-Type": "application/json"}
        if self._api_key:
            headers["x-goog-api-key"] = self._api_key
        extra_headers = (extra_params or {}).get("extra_headers")
        if isinstance(extra_headers, dict):
            for k, v in extra_headers.items():
                headers[str(k)] = str(v)
        return headers

    def _build_client(self) -> httpx.AsyncClient:
        kwargs: Dict[str, Any] = {"timeout": float(self._timeout_sec)}
        if self._transport is not None:
            kwargs["transport"] = self._transport
        return httpx.AsyncClient(**kwargs)

    @staticmethod
    def _build_body(
        messages: List[Dict[str, str]],
        *,
        system_prompt: str,
        extra_params: Optional[Dict[str, Any]],
        json_mode: bool,
    ) -> Dict[str, Any]:
        contents: List[Dict[str, Any]] = []
        for msg in messages:
            text = str(msg.get("content", ""))
            if not text:
                continue
            role = "model" if msg.get("role") == "assistant" else "user"
            contents.append({"role": role, "parts": [{"text": text}]})

        body: Dict[str, Any] = {"contents": contents}
        if system_prompt.strip():
            body["systemInstruction"] = {"parts": [{"text": system_prompt.strip()}]}

        gen_cfg: Dict[str, Any] = {}
        params = extra_params or {}
        if params.get("temperature") is not None:
            gen_cfg["temperature"] = params["temperature"]
        if params.get("top_p") is not None:
            gen_cfg["topP"] = params["top_p"]
        if params.get("max_tokens") is not None:
            gen_cfg["maxOutputTokens"] = int(params["max_tokens"])
        if json_mode:
            gen_cfg["responseMimeType"] = "application/json"
        if gen_cfg:
            body["generationConfig"] = gen_cfg
        return body

    @staticmethod
    def _raise_for_status(response: httpx.Response) -> None:
        if response.status_code == 429:
            raise LLMRateLimitError(f"Gemini rate limited: {_extract_gemini_error(response)}")
        if response.status_code >= 400:
            raise LLMUpstreamError(
                f"Gemini request failed ({response.status_code}): {_extract_gemini_error(response)}"
            )

    async def stream_chat(
        self,
        messages: List[Dict[str, str]],
        model: str,
        *,
        system_prompt: str = "",
        external_conversation_id: str = "",
        extra_params: Optional[Dict[str, Any]] = None,
    ) -> AsyncIterator[StreamEvent]:
        """Stream assistant tokens from Gemini `streamGenerateContent?alt=sse`.

        Args:
            messages: Conversation turns.
            model: Gemini model identifier (e.g. `gemini-2.5-flash`).
            system_prompt: Optional system instruction.
            external_conversation_id: Preserved in emitted events.
            extra_params: Optional generation/header overrides.

        Yields:
            StreamEvent: `init`, `delta`, and `done` events.

        Raises:
            LLMConfigError: When credentials are missing.
            LLMTimeoutError: On request timeout.
            LLMRateLimitError: On HTTP 429.
            LLMUpstreamError: On HTTP or transport errors.
        """
        self._validate_credentials()
        headers = self._build_headers(extra_params)
        body = self._build_body(messages, system_prompt=system_prompt, extra_params=extra_params, json_mode=False)
        model_id = model.strip().removeprefix("models/")
        url = f"{self._base_url}/models/{model_id}:streamGenerateContent?alt=sse"
        yield StreamEvent(type="init", conversation_id=external_conversation_id)

        usage: Dict[str, Any] = {}
        try:
            async with self._build_client() as client:
                async with client.stream("POST", url, headers=headers, json=body) as response:
                    if response.status_code >= 400:
                        await response.aread()
                        self._raise_for_status(response)
                    async for raw_line in response.aiter_lines():
                        line = raw_line.strip()
                        if not line.startswith("data:"):
                            continue
                        data_str = line[5:].strip()
                        if not data_str or data_str == "[DONE]":
                            continue
                        chunk = json.loads(data_str)
                        if isinstance(chunk.get("usageMetadata"), dict):
                            usage = chunk["usageMetadata"]
                        text = _extract_candidate_text(chunk)
                        if text:
                            yield StreamEvent(type="delta", text=text)
            yield StreamEvent(type="done", conversation_id=external_conversation_id, usage=usage)
        except httpx.TimeoutException as exc:
            raise LLMTimeoutError(f"Gemini stream timed out: {exc}") from exc
        except (LLMConfigError, LLMRateLimitError, LLMTimeoutError, LLMUpstreamError):
            raise
        except Exception as exc:
            raise LLMUpstreamError(f"Gemini stream failed: {exc}") from exc

    async def complete_json(
        self,
        messages: List[Dict[str, str]],
        model: str,
        *,
        system_prompt: str = "",
        extra_params: Optional[Dict[str, Any]] = None,
    ) -> Tuple[Dict[str, Any], Dict[str, Any]]:
        """Execute a structured JSON completion via Gemini `generateContent`.

        Args:
            messages: Conversation turns.
            model: Target Gemini model identifier.
            system_prompt: Optional system instruction.
            extra_params: Optional generation/header overrides.

        Returns:
            Tuple[Dict[str, Any], Dict[str, Any]]: `(parsed_json, usage_metadata)`.

        Raises:
            LLMConfigError: When credentials are missing.
            LLMTimeoutError: On request timeout.
            LLMRateLimitError: On HTTP 429.
            LLMUpstreamError: On HTTP failure or unparseable JSON output.
        """
        self._validate_credentials()
        headers = self._build_headers(extra_params)
        body = self._build_body(messages, system_prompt=system_prompt, extra_params=extra_params, json_mode=True)
        model_id = model.strip().removeprefix("models/")
        url = f"{self._base_url}/models/{model_id}:generateContent"

        try:
            async with self._build_client() as client:
                response = await client.post(url, headers=headers, json=body)
                self._raise_for_status(response)
                payload = response.json()
        except httpx.TimeoutException as exc:
            raise LLMTimeoutError(f"Gemini request timed out: {exc}") from exc
        except (LLMConfigError, LLMRateLimitError, LLMTimeoutError, LLMUpstreamError):
            raise
        except Exception as exc:
            raise LLMUpstreamError(f"Gemini request failed: {exc}") from exc

        text = _extract_candidate_text(payload)
        usage = payload.get("usageMetadata") if isinstance(payload.get("usageMetadata"), dict) else {}
        return extract_json_object(text), usage

    async def list_models(self, extra_params: Optional[Dict[str, Any]] = None) -> List[str]:
        """List available `generateContent` Gemini models from Google AI Studio.

        Args:
            extra_params: Optional parameters containing `extra_headers`.

        Returns:
            List[str]: Sorted distinct model names without the `models/` prefix.

        Raises:
            LLMConfigError: When credentials are missing.
            LLMTimeoutError: On request timeout.
            LLMRateLimitError: On HTTP 429.
            LLMUpstreamError: On HTTP error.
        """
        self._validate_credentials()
        headers = self._build_headers(extra_params)
        url = f"{self._base_url}/models"
        try:
            async with self._build_client() as client:
                response = await client.get(url, headers=headers)
                self._raise_for_status(response)
                payload = response.json()
        except httpx.TimeoutException as exc:
            raise LLMTimeoutError(f"Gemini list_models timed out: {exc}") from exc
        except (LLMConfigError, LLMRateLimitError, LLMTimeoutError, LLMUpstreamError):
            raise
        except Exception as exc:
            raise LLMUpstreamError(f"Gemini list_models failed: {exc}") from exc

        models: List[str] = []
        for entry in payload.get("models") or []:
            if not isinstance(entry, dict):
                continue
            methods = entry.get("supportedGenerationMethods")
            if isinstance(methods, list) and "generateContent" not in methods:
                continue
            name = str(entry.get("name") or "").strip().removeprefix("models/")
            if name:
                models.append(name)
        return sorted(set(models))
