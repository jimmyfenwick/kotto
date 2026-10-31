"""DeepSeek Chat Completions streaming adapter. No tool execution or retries."""

import json
from collections.abc import AsyncIterator
from typing import Protocol

import httpx

from kotto.config import Settings
from kotto.contracts.event import ModelEvent


class ModelError(Exception):
    """Safe diagnostic: never includes raw response bodies or credentials."""

    def __init__(self, kind: str, message: str):
        super().__init__(message)
        self.kind = kind


class ModelGateway(Protocol):
    def stream(
        self, messages: list[dict], *, tools: list[dict] | None = None
    ) -> AsyncIterator[ModelEvent]: ...


async def _sse_data(response: httpx.Response) -> AsyncIterator[str]:
    buffer = b""
    data = []
    size = 0
    limit = 1024 * 1024
    async for chunk in response.aiter_bytes():
        buffer += chunk
        while b"\n" in buffer:
            line, buffer = buffer.split(b"\n", 1)
            size += len(line)
            if size > limit:
                raise ModelError("protocol", "Model event exceeds the size limit.")
            line = line.rstrip(b"\r")
            if not line:
                if data:
                    yield b"\n".join(data).decode("utf-8")
                data, size = [], 0
            elif line.startswith(b"data:"):
                data.append(line[5:].removeprefix(b" "))
        if len(buffer) + size > limit:
            raise ModelError("protocol", "Model event exceeds the size limit.")
    # A partial last SSE event is not a successful stream terminator.
    raise ModelError("interrupted", "Model stream ended without a complete DONE marker.")


class DeepSeekGateway:
    def __init__(self, settings: Settings, *, client: httpx.AsyncClient | None = None):
        self.settings = settings
        self._client = client

    async def stream(
        self, messages: list[dict], *, tools: list[dict] | None = None
    ) -> AsyncIterator[ModelEvent]:
        if not self.settings.api_key:
            raise ModelError("configuration", "Configure KOTTO_API_KEY or DEEPSEEK_API_KEY first.")
        if not messages:
            raise ModelError("request", "At least one message is required.")
        if self._client is not None:
            async for event in self._stream(self._client, messages, tools):
                yield event
        else:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(60, connect=15), trust_env=False
            ) as client:
                async for event in self._stream(client, messages, tools):
                    yield event

    async def _stream(self, client, messages, tools):
        body = {
            "model": self.settings.model,
            "messages": messages,
            "stream": True,
            "stream_options": {"include_usage": True},
            "thinking": {"type": "disabled"},
        }
        if tools:
            body["tools"] = tools
        try:
            async with client.stream(
                "POST",
                self.settings.base_url + "/chat/completions",
                json=body,
                headers={"Authorization": "Bearer " + self.settings.api_key},
            ) as response:
                if response.status_code != 200:
                    status = response.status_code
                    kind = (
                        "authentication"
                        if status in {401, 403}
                        else "rate_limit"
                        if status == 429
                        else "server"
                        if status >= 500
                        else "request"
                    )
                    raise ModelError(kind, f"Model request failed with HTTP {status} ({kind}).")
                text, reasoning, calls = "", "", {}
                finish = None
                async for raw in _sse_data(response):
                    if raw == "[DONE]":
                        if finish not in {"stop", "tool_calls"}:
                            raise ModelError(
                                "incomplete", "Model response has no successful completion reason."
                            )
                        message = {"role": "assistant", "content": text or None}
                        if reasoning:
                            message["reasoning_content"] = reasoning
                        if calls:
                            ids = set()
                            ordered = [calls[i] for i in sorted(calls)]
                            for call in ordered:
                                if (
                                    not call["id"]
                                    or not call["function"]["name"]
                                    or call["id"] in ids
                                ):
                                    raise ModelError(
                                        "protocol", "Tool call identity is incomplete or repeated."
                                    )
                                if not isinstance(json.loads(call["function"]["arguments"]), dict):
                                    raise ModelError(
                                        "protocol", "Tool arguments must be a JSON object."
                                    )
                                ids.add(call["id"])
                            if finish != "tool_calls":
                                raise ModelError(
                                    "protocol", "Tool calls have an inconsistent finish reason."
                                )
                            message["tool_calls"] = ordered
                        elif finish == "tool_calls":
                            raise ModelError(
                                "protocol", "Missing tool calls in completed response."
                            )
                        yield ModelEvent("message", message)
                        yield ModelEvent("finished", {"reason": finish})
                        return
                    payload = json.loads(raw)
                    if not isinstance(payload, dict) or "error" in payload:
                        raise ModelError("protocol", "Invalid model event.")
                    if payload.get("usage") is not None:
                        usage = payload["usage"]
                        if not isinstance(usage, dict):
                            raise ModelError("protocol", "Invalid model usage event.")
                        yield ModelEvent("usage", usage)
                    choices = payload.get("choices")
                    if not isinstance(choices, list) or len(choices) > 1:
                        raise ModelError("protocol", "Expected one model choice or a usage event.")
                    if not choices:
                        continue
                    choice = choices[0]
                    if choice.get("index", 0) != 0 or finish is not None:
                        raise ModelError("protocol", "Unexpected model choice after completion.")
                    delta = choice.get("delta", {})
                    if not isinstance(delta, dict):
                        raise ModelError("protocol", "Invalid model delta.")
                    for name, kind in [
                        ("content", "text_delta"),
                        ("reasoning_content", "reasoning_delta"),
                    ]:
                        part = delta.get(name)
                        if part is not None:
                            if not isinstance(part, str):
                                raise ModelError("protocol", "Invalid model text delta.")
                            if name == "content":
                                text += part
                            else:
                                reasoning += part
                            if part:
                                yield ModelEvent(kind, {"text": part})
                    for fragment in delta.get("tool_calls", []):
                        index = fragment["index"]
                        if not isinstance(index, int) or index < 0 or index > 127:
                            raise ModelError("protocol", "Invalid tool call index.")
                        call = calls.setdefault(
                            index,
                            {
                                "id": "",
                                "type": "function",
                                "function": {"name": "", "arguments": ""},
                            },
                        )
                        if fragment.get("type", "function") != "function":
                            raise ModelError("protocol", "Unsupported tool call type.")
                        if fragment.get("id"):
                            call["id"] += fragment["id"]
                        for name in ["name", "arguments"]:
                            call["function"][name] += fragment.get("function", {}).get(name, "")
                    if (
                        len(text)
                        + len(reasoning)
                        + sum(len(c["function"]["arguments"]) for c in calls.values())
                        > 4 * 1024 * 1024
                    ):
                        raise ModelError("protocol", "Model output exceeds the size limit.")
                    if choice.get("finish_reason") is not None:
                        finish = choice["finish_reason"]
        except httpx.TimeoutException:
            raise ModelError("timeout", "Model connection or response timed out.") from None
        except httpx.HTTPError:
            raise ModelError("network", "Model connection failed or was interrupted.") from None
        except (ValueError, KeyError, TypeError, IndexError, AttributeError):
            raise ModelError(
                "protocol", "Malformed model response; partial output is not complete."
            ) from None
