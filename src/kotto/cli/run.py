"""Agent CLI rendering; model/tool orchestration lives in runtime."""
import json
import sys
from kotto.model.gateway import DeepSeekGateway
from kotto.runtime.agent import Agent
from kotto.tools.executor import ToolExecutor


async def run(settings, args):
    agent = Agent(DeepSeekGateway(settings), ToolExecutor(settings.workspace), max_rounds=args.max_rounds)
    result = 1
    async for event in agent.run(args.prompt):
        if args.json:
            print(json.dumps({"event": event.kind, "data": event.data}, ensure_ascii=False), flush=True)
        elif event.kind == "text_delta": print(event.data["text"], end="", flush=True)
        elif event.kind == "tool_end": print(f"\n[{event.data['name']}: {event.data['status']}]", file=sys.stderr)
        elif event.kind == "error": print(event.data["message"], file=sys.stderr)
        if event.kind == "run_end": result = 0 if event.data["reason"] == "completed" else 1
    if not args.json: print()
    return result
