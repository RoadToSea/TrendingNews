"""Unified LLM gateway protocol, normalized stream events, and error hierarchy."""

from dataclasses import dataclass, field
import json
import re
from typing import Any, AsyncIterator, Dict, List, Literal, Optional, Protocol, Tuple


class LLMGatewayError(Exception):
    """Base error raised by LLM adapters and gateway resolution."""

    def __init__(self, code: str, message: str, status_code: int = 502) -> None:
        """Initialize structured gateway error.

        Args:
            code: Machine-readable error code.
            message: Human-readable description.
            status_code: Recommended HTTP status code.
        """
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


class LLMConfigError(LLMGatewayError):
    """Raised when no valid/enabled AI slot exists or required parameters are missing."""

    def __init__(self, message: str, code: str = "ai_config_error") -> None:
        super().__init__(code=code, message=message, status_code=400)


class LLMRateLimitError(LLMGatewayError):
    """Raised when upstream rate limits or local CLI concurrency limits are hit."""

    def __init__(self, message: str, code: str = "ai_rate_limited") -> None:
        super().__init__(code=code, message=message, status_code=429)


class LLMTimeoutError(LLMGatewayError):
    """Raised when an upstream LLM HTTP request or CLI subprocess times out."""

    def __init__(self, message: str, code: str = "ai_timeout") -> None:
        super().__init__(code=code, message=message, status_code=504)


class LLMUpstreamError(LLMGatewayError):
    """Raised when an upstream AI provider returns an unexpected error or malformed response."""

    def __init__(self, message: str, code: str = "ai_upstream_error") -> None:
        super().__init__(code=code, message=message, status_code=502)


@dataclass
class StreamEvent:
    """Normalized streaming event emitted by all LLM gateway adapters."""

    type: Literal["init", "delta", "done", "error"]
    text: str = ""
    conversation_id: str = ""
    usage: Dict[str, Any] = field(default_factory=dict)
    code: str = ""
    message: str = ""


class LLMGateway(Protocol):
    """Unified asynchronous interface implemented by OpenAI, Anthropic, and Antigravity adapters."""

    async def stream_chat(
        self,
        messages: List[Dict[str, str]],
        model: str,
        *,
        system_prompt: str = "",
        external_conversation_id: str = "",
        extra_params: Optional[Dict[str, Any]] = None,
    ) -> AsyncIterator[StreamEvent]:
        """Stream chat completion tokens as normalized `StreamEvent` objects."""
        ...

    async def complete_json(
        self,
        messages: List[Dict[str, str]],
        model: str,
        *,
        system_prompt: str = "",
        extra_params: Optional[Dict[str, Any]] = None,
    ) -> Tuple[Dict[str, Any], Dict[str, Any]]:
        """Execute a structured JSON completion returning `(parsed_json, usage_dict)`."""
        ...

    async def list_models(
        self,
        extra_params: Optional[Dict[str, Any]] = None,
    ) -> List[str]:
        """Discover selectable model identifiers exposed by the provider endpoint."""
        ...


_FENCE_RE = re.compile(r"```(?:json)?\s*([\s\S]*?)```", re.IGNORECASE)


def extract_json_object(raw_text: str) -> Dict[str, Any]:
    """Parse a JSON object from model output, tolerating Markdown code fences.

    Args:
        raw_text: Raw text returned by an LLM.

    Returns:
        Dict[str, Any]: Decoded top-level JSON dictionary.

    Raises:
        LLMUpstreamError: If no valid JSON object can be extracted.
    """
    text = (raw_text or "").strip()
    if not text:
        raise LLMUpstreamError("Model returned empty response when JSON was expected")

    candidates = [text]
    fence_match = _FENCE_RE.search(text)
    if fence_match:
        candidates.insert(0, fence_match.group(1).strip())

    first_brace = text.find("{")
    last_brace = text.rfind("}")
    if first_brace != -1 and last_brace > first_brace:
        candidates.append(text[first_brace : last_brace + 1])

    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            continue

    raise LLMUpstreamError(f"Failed to parse JSON object from model output: {text[:160]}")