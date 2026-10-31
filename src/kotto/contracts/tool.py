"""Tool contracts; results always correlate with the originating call."""

import json
from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class ToolResult:
    call_id: str
    status: Literal["ok", "error", "cancelled", "unknown"]
    content: dict

    def message(self):
        return {
            "role": "tool",
            "tool_call_id": self.call_id,
            "content": json.dumps(
                {"status": self.status, "content": self.content}, ensure_ascii=False
            ),
        }
