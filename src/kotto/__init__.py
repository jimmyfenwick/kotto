"""KOTTO: a lightweight, extensible Python Agent Harness."""

__version__ = "0.1.0"

from kotto.config import Settings
from kotto.contracts.event import AgentEvent, ModelEvent
from kotto.contracts.tool import ToolResult
from kotto.tools.executor import Tool, ToolExecutor
from kotto.tools.policy import Policy
from kotto.session.store import Journal
from kotto.model.gateway import DeepSeekGateway
from kotto.runtime.agent import Agent
from kotto.bootstrap import create_agent

__all__ = [
    "Settings",
    "AgentEvent",
    "ModelEvent",
    "ToolResult",
    "Tool",
    "ToolExecutor",
    "Policy",
    "Journal",
    "DeepSeekGateway",
    "Agent",
    "create_agent",
    "__version__",
]
