"""One streaming conversation turn; no persistence or tool execution yet."""

import json
import sys

from kotto.model.gateway import DeepSeekGateway, ModelError


async def chat(settings, prompt: str, *, json_mode: bool = False, gateway=None) -> int:
    gateway = gateway or DeepSeekGateway(settings)
    had_text = False
    try:
        async for event in gateway.stream([{"role": "user", "content": prompt}]):
            if json_mode:
                print(
                    json.dumps({"event": event.kind, "data": event.data}, ensure_ascii=False),
                    flush=True,
                )
            elif event.kind == "text_delta":
                print(event.data["text"], end="", flush=True)
                had_text = True
        if had_text and not json_mode:
            print()
        return 0
    except ModelError as error:
        if had_text and not json_mode:
            print()
        if json_mode:
            print(
                json.dumps(
                    {
                        "event": "error",
                        "data": {"kind": error.kind, "message": str(error), "complete": False},
                    }
                ),
                flush=True,
            )
        else:
            print(f"Model error ({error.kind}): {error}. Output is incomplete.", file=sys.stderr)
        return 2 if error.kind == "configuration" else 1
