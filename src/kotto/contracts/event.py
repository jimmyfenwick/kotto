"""Model events are independent of terminal rendering and session storage."""

from dataclasses import dataclass
from typing import Any, Literal


@dataclass(frozen=True)
class ModelEvent:
    kind: Literal["text_delta", "reasoning_delta", "usage", "message", "finished"]
    data: dict[str, Any]


@dataclass(frozen=True)
class AgentEvent:
    kind: str
    data: dict[str, Any]
