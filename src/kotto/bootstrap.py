"""Composition root: concrete dependencies are assembled in one place."""

from kotto.model.gateway import DeepSeekGateway
from kotto.runtime.agent import Agent
from kotto.tools.executor import ToolExecutor
from kotto.extensions.host import ExtensionHost, load_skill


def create_agent(
    settings, *, model=None, policy=None, journal=None, extensions=(), skills=(), **limits
):
    tools = ToolExecutor(settings.workspace, policy=policy)
    host = ExtensionHost(tools)
    try:
        for path in extensions:
            host.load(path)
        agent = Agent(model or DeepSeekGateway(settings), tools, journal=journal, **limits)
        agent.context.skills = [load_skill(path) for path in skills]
        agent.extensions = host
        return agent
    except BaseException:
        host.close()
        raise
