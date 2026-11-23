"""Antigravity CLI (`agy --output-format stream-json`) subprocess adapter with concurrency guard."""

import asyncio
import json
import os
from pathlib import Path
from typing import Any, AsyncIterator, Dict, List, Optional, Sequence, Tuple

from app.services.ai_gateway.base import (
    LLMRateLimitError,
    LLMTimeoutError,
    LLMUpstreamError,
    StreamEvent,
    extract_json_object,
)


def _format_prompt(
    messages: List[Dict[str, str]],
    system_prompt: str,
    external_conversation_id: str,
) -> str:
    # When continuing an agy conversation, agy already retains prior turns server/session-side.
    if external_conversation_id and messages:
        last_user = messages[-1].get("content", "")
        if system_prompt.strip():
            return f"[System Guidance]\n{system_prompt.strip()}\n\n{last_user}"
        return last_user

    sections: List[str] = []
    if system_prompt.strip():
        sections.append(f"[System]\n{system_prompt.strip()}")
    for msg in messages:
        role = msg.get("role", "user").capitalize()
        content = str(msg.get("content", "")).strip()
        if content:
            sections.append(f"[{role}]\n{content}")
    return "\n\n".join(sections)


def _build_subprocess_env(proxy_url: str) -> Dict[str, str]:
    env = dict(os.environ)
    if proxy_url.strip():
        proxy = proxy_url.strip()
        env["HTTP_PROXY"] = proxy
        env["HTTPS_PROXY"] = proxy
        env["http_proxy"] = proxy
        env["https_proxy"] = proxy
    return env


async def _terminate_process(proc: asyncio.subprocess.Process) -> None:
    if proc.returncode is not None:
        return
    try:
        proc.terminate()
        await asyncio.wait_for(proc.wait(), timeout=2.0)
    except (ProcessLookupError, asyncio.TimeoutError):
        try:
            proc.kill()
            await proc.wait()
        except ProcessLookupError:
            pass


class AntigravityCLIAdapter:
    """`LLMGateway` adapter executing `agy --output-format stream-json` inside an isolated sandbox cwd."""

    def __init__(
        self,
        *,
        agy_bin: str,
        proxy_url: str,
        workspace: Path,
        timeout_sec: int,
        semaphore: asyncio.Semaphore,
        extra_args: Optional[Sequence[str]] = None,
    ) -> None:
        """Initialize the Antigravity CLI adapter.

        Args:
            agy_bin: Executable path or command name for `agy`.
            proxy_url: Explicit HTTP/HTTPS proxy URL passed to subprocess environment.
            workspace: Isolated empty working directory preventing repository scanning.
            timeout_sec: Timeout in seconds enforced by both `--print-timeout` and asyncio wait.
            semaphore: Process-wide semaphore bounding simultaneous `agy` invocations.
            extra_args: Optional prefix arguments inserted right after `agy_bin` (primarily for testing).
        """
        self._agy_bin = agy_bin
        self._proxy_url = proxy_url
        self._workspace = workspace
        self._timeout_sec = max(10, int(timeout_sec))
        self._semaphore = semaphore
        self._extra_args = list(extra_args or [])

    def build_command(
        self,
        *,
        model: str,
        prompt: str,
        external_conversation_id: str = "",
    ) -> List[str]:
        """Construct the sandboxed `agy` CLI command line without dangerous permission overrides.

        Args:
            model: Antigravity model identifier.
            prompt: Formatted prompt text passed via trailing `-p=...`.
            external_conversation_id: Optional prior conversation ID for `--conversation` continuation.

        Returns:
            List[str]: Subprocess argument list.
        """
        cmd: List[str] = [self._agy_bin, *self._extra_args]
        cmd.extend(
            [
                "--output-format",
                "stream-json",
                "--model",
                model,
                "--sandbox",
                "--disable-slash-commands",
                "--print-timeout",
                f"{self._timeout_sec}s",
            ]
        )
        if external_conversation_id.strip():
            cmd.extend(["--conversation", external_conversation_id.strip()])
        # Prompt must stay attached with `=` at the end so agy does not confuse flag order.
        cmd.append(f"-p={prompt}")
        return cmd

    async def _acquire_slot(self) -> None:
        try:
            await asyncio.wait_for(self._semaphore.acquire(), timeout=5.0)
        except asyncio.TimeoutError as exc:
            raise LLMRateLimitError("Antigravity CLI concurrency limit reached, try again shortly") from exc

    async def stream_chat(
        self,
        messages: List[Dict[str, str]],
        model: str,
        *,
        system_prompt: str = "",
        external_conversation_id: str = "",
        extra_params: Optional[Dict[str, Any]] = None,
    ) -> AsyncIterator[StreamEvent]:
        """Run `agy` asynchronously and map NDJSON output lines to `StreamEvent` items.

        Args:
            messages: Conversation turns.
            model: Target Antigravity model (e.g. `gemini-3.8-flash-medium`).
            system_prompt: Optional system guidance.
            external_conversation_id: Existing `agy` conversation ID to resume.
            extra_params: Optional overrides (`print_timeout` allowed).

        Yields:
            StreamEvent: Normalized `init`, `delta`, and `done` events.

        Raises:
            LLMRateLimitError: When concurrency semaphore cannot be acquired in time.
            LLMTimeoutError: When subprocess execution exceeds timeout.
            LLMUpstreamError: When binary launch fails or `agy` reports an error/non-zero exit.
        """
        del extra_params
        self._workspace.mkdir(parents=True, exist_ok=True)
        prompt = _format_prompt(messages, system_prompt, external_conversation_id)
        cmd = self.build_command(
            model=model,
            prompt=prompt,
            external_conversation_id=external_conversation_id,
        )
        env = _build_subprocess_env(self._proxy_url)

        await self._acquire_slot()
        proc: Optional[asyncio.subprocess.Process] = None
        try:
            try:
                proc = await asyncio.create_subprocess_exec(
                    *cmd,
                    cwd=str(self._workspace),
                    env=env,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    limit=2 * 1024 * 1024,
                )
            except FileNotFoundError as exc:
                raise LLMUpstreamError(f"Antigravity executable not found: {self._agy_bin}") from exc

            async for event in self._consume_ndjson_stream(proc, external_conversation_id):
                yield event
        finally:
            if proc is not None:
                await _terminate_process(proc)
            self._semaphore.release()

    async def _consume_ndjson_stream(
        self,
        proc: asyncio.subprocess.Process,
        initial_conv_id: str,
    ) -> AsyncIterator[StreamEvent]:
        assert proc.stdout is not None and proc.stderr is not None
        deadline = asyncio.get_running_loop().time() + float(self._timeout_sec) + 5.0
        conv_id = initial_conv_id
        emitted_delta = False
        result_seen = False

        while True:
            remaining = deadline - asyncio.get_running_loop().time()
            if remaining <= 0:
                raise LLMTimeoutError(f"Antigravity CLI timed out after {self._timeout_sec}s")
            try:
                raw_line = await asyncio.wait_for(proc.stdout.readline(), timeout=remaining)
            except asyncio.TimeoutError as exc:
                raise LLMTimeoutError(f"Antigravity CLI timed out after {self._timeout_sec}s") from exc

            if not raw_line:
                break
            line = raw_line.decode("utf-8", errors="replace").strip()
            if not line:
                continue

            event, conv_id, delta_added, is_result = self._parse_ndjson_line(line, conv_id, emitted_delta)
            emitted_delta = emitted_delta or delta_added
            result_seen = result_seen or is_result
            if event is not None:
                if is_result and not emitted_delta and event.text:
                    yield StreamEvent(type="delta", text=event.text, conversation_id=conv_id)
                yield event

        return_code = await proc.wait()
        stderr_text = (await proc.stderr.read()).decode("utf-8", errors="replace").strip()
        if return_code != 0:
            raise LLMUpstreamError(f"Antigravity CLI exited with code {return_code}: {stderr_text[:240]}")
        if not result_seen:
            yield StreamEvent(type="done", conversation_id=conv_id, usage={})

    @staticmethod
    def _parse_ndjson_line(
        line: str,
        current_conv_id: str,
        emitted_delta: bool,
    ) -> Tuple[Optional[StreamEvent], str, bool, bool]:
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            return None, current_conv_id, False, False

        ev_type = payload.get("event")
        if ev_type == "init":
            conv_id = str(payload.get("conversation_id") or current_conv_id)
            return StreamEvent(type="init", conversation_id=conv_id), conv_id, False, False

        if ev_type == "step_update":
            step = payload.get("step_update") or {}
            conv_id = str(step.get("conversation_id") or current_conv_id)
            if step.get("step_type") == "agent_response":
                delta = str(step.get("text_delta") or "")
                if delta:
                    return StreamEvent(type="delta", text=delta, conversation_id=conv_id), conv_id, True, False
            return None, conv_id, False, False

        if ev_type == "result":
            res = payload.get("result") or {}
            conv_id = str(res.get("conversation_id") or current_conv_id)
            status_val = str(res.get("status") or "").upper()
            if status_val and status_val != "SUCCESS":
                err_msg = str(res.get("error") or res.get("response") or status_val)
                raise LLMUpstreamError(f"Antigravity result error ({status_val}): {err_msg}")
            full_response = "" if emitted_delta else str(res.get("response") or "")
            usage = res.get("usage") if isinstance(res.get("usage"), dict) else {}
            return (
                StreamEvent(type="done", text=full_response, conversation_id=conv_id, usage=usage),
                conv_id,
                bool(full_response),
                True,
            )

        return None, current_conv_id, False, False

    async def complete_json(
        self,
        messages: List[Dict[str, str]],
        model: str,
        *,
        system_prompt: str = "",
        extra_params: Optional[Dict[str, Any]] = None,
    ) -> Tuple[Dict[str, Any], Dict[str, Any]]:
        """Execute an `agy` invocation and parse the aggregated response as JSON.

        Args:
            messages: Conversation turns.
            model: Antigravity model name.
            system_prompt: Optional system guidance.
            extra_params: Optional overrides.

        Returns:
            Tuple[Dict[str, Any], Dict[str, Any]]: `(parsed_json, usage_dict)`.

        Raises:
            LLMGatewayError: On CLI error, timeout, concurrency limit, or malformed JSON output.
        """
        chunks: List[str] = []
        usage: Dict[str, Any] = {}
        async for ev in self.stream_chat(
            messages,
            model,
            system_prompt=system_prompt,
            extra_params=extra_params,
        ):
            if ev.type == "delta" and ev.text:
                chunks.append(ev.text)
            elif ev.type == "done":
                usage = ev.usage
        return extract_json_object("".join(chunks)), usage

    async def list_models(self, extra_params: Optional[Dict[str, Any]] = None) -> List[str]:
        """Discover available models by invoking `agy models` inside the sandbox workspace.

        Args:
            extra_params: Unused; kept for `LLMGateway` protocol compatibility.

        Returns:
            List[str]: Discovered Antigravity model IDs.

        Raises:
            LLMGatewayError: On CLI missing, concurrency limit, timeout, or non-zero exit.
        """
        del extra_params
        self._workspace.mkdir(parents=True, exist_ok=True)
        cmd = [self._agy_bin, *self._extra_args, "models"]
        env = _build_subprocess_env(self._proxy_url)

        await self._acquire_slot()
        proc: Optional[asyncio.subprocess.Process] = None
        try:
            try:
                proc = await asyncio.create_subprocess_exec(
                    *cmd,
                    cwd=str(self._workspace),
                    env=env,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
            except FileNotFoundError as exc:
                raise LLMUpstreamError(f"Antigravity executable not found: {self._agy_bin}") from exc

            try:
                stdout_b, stderr_b = await asyncio.wait_for(proc.communicate(), timeout=20.0)
            except asyncio.TimeoutError as exc:
                raise LLMTimeoutError("Antigravity `agy models` timed out") from exc

            if proc.returncode != 0:
                err = stderr_b.decode("utf-8", errors="replace").strip()
                raise LLMUpstreamError(f"Antigravity `agy models` failed: {err[:200]}")

            output = stdout_b.decode("utf-8", errors="replace")
            return self._parse_models_output(output)
        finally:
            if proc is not None:
                await _terminate_process(proc)
            self._semaphore.release()

    @staticmethod
    def _parse_models_output(raw_output: str) -> List[str]:
        import re

        found: List[str] = []
        seen = set()
        for line in raw_output.splitlines():
            clean = line.strip()
            if not clean or clean.endswith(":") or clean.startswith(("-", "=", "Model", "NAME", "Available", "Fetching")):
                continue
            token = re.split(r"[\s,|]+", clean)[0].strip("*` ")
            if (
                re.match(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{2,}$", token)
                and any(ch in token for ch in ("-", ".", "/"))
                and token not in seen
            ):
                seen.add(token)
                found.append(token)
        return found