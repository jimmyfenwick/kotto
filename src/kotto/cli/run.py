"""Agent CLI rendering; model/tool orchestration lives in runtime."""
import json
import sys
import asyncio
from pathlib import Path
from kotto.model.gateway import DeepSeekGateway
from kotto.runtime.agent import Agent
from kotto.tools.executor import ToolExecutor
from kotto.session.store import Journal, SessionError
from kotto.tools.policy import Policy


async def run(settings, args):
    if args.ask and (args.json or not sys.stdin.isatty()): raise SessionError("Interactive approval requires a terminal and text mode.")
    async def approve(tool, parameters):
        print(f"Authorize {tool.effect} tool {tool.name}? Arguments: {json.dumps(parameters, ensure_ascii=False)[:2000]}", file=sys.stderr)
        answer = await asyncio.to_thread(input, "Type yes to authorize: ")
        return answer.strip().lower() == "yes"
    policy = Policy(allow_write=args.allow_write, approve=approve if args.ask else None)
    with Journal(Path(args.session_root), args.session) as store:
        config = next((e["data"] for e in store.events if e["kind"] == "config"), None)
        if config and config["workspace"] != str(settings.workspace):
            raise SessionError("Session belongs to another workspace.")
        if config and ((args.allow_write and not config.get("allow_write")) or (args.ask and not config.get("ask"))):
            raise SessionError("Cannot elevate a resumed session; start a new session with explicit permissions.")
        if not config: store.append("config", {"workspace": str(settings.workspace), "allow_write": args.allow_write, "ask": args.ask})
        if args.acknowledge_unknown: store.acknowledge_unknown()
        agent = Agent(DeepSeekGateway(settings), ToolExecutor(settings.workspace, policy=policy), max_rounds=args.max_rounds, journal=store)
        if args.json: print(json.dumps({"event": "session", "data": {"session_id": store.session_id}}), flush=True)
        else: print(f"Session: {store.session_id}", file=sys.stderr)
        return await render(agent, args)


async def render(agent, args):
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
