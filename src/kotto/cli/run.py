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
    if args.interactive and (args.json or args.ask or not sys.stdin.isatty()): raise SessionError("Interactive steering needs a terminal, text mode, and no --ask.")
    async def approve(tool, parameters):
        print(f"Authorize {tool.effect} tool {tool.name}? Arguments: {json.dumps(parameters, ensure_ascii=False)[:2000]}", file=sys.stderr)
        print("Type yes to authorize: ",end='',file=sys.stderr,flush=True)
        loop=asyncio.get_running_loop();future=loop.create_future()
        def ready():
            if not future.done():future.set_result(sys.stdin.readline())
        loop.add_reader(sys.stdin.fileno(),ready)
        try:answer=await future
        finally:loop.remove_reader(sys.stdin.fileno())
        return answer.strip().lower() == "yes"
    policy = Policy(allow_write=args.allow_write, allow_shell=args.allow_shell, approve=approve if args.ask else None)
    with Journal(Path(args.session_root), args.session) as store:
        config = next((e["data"] for e in store.events if e["kind"] == "config"), None)
        if config and config["workspace"] != str(settings.workspace):
            raise SessionError("Session belongs to another workspace.")
        if config and ((args.allow_write and not config.get("allow_write")) or (args.allow_shell and not config.get("allow_shell")) or (args.ask and not config.get("ask"))):
            raise SessionError("Cannot elevate a resumed session; start a new session with explicit permissions.")
        if not config: store.append("config", {"workspace": str(settings.workspace), "allow_write": args.allow_write, "allow_shell": args.allow_shell, "ask": args.ask})
        if args.acknowledge_unknown: store.acknowledge_unknown()
        agent = Agent(DeepSeekGateway(settings), ToolExecutor(settings.workspace, policy=policy), max_rounds=args.max_rounds, journal=store, timeout=args.timeout,max_tool_calls=args.max_tool_calls,max_tokens=args.max_total_tokens)
        if args.json: print(json.dumps({"event": "session", "data": {"session_id": store.session_id}}), flush=True)
        else: print(f"Session: {store.session_id}", file=sys.stderr)
        return await render(agent, args)


async def render(agent, args):
    loop=asyncio.get_running_loop()
    controls=set()
    reader=False
    async def control(line):
        try:
            if line.strip()=='/cancel':await agent.cancel()
            elif line.startswith('/steer '):await agent.steer(line[7:].strip())
            else:print('Use /steer TEXT or /cancel.',file=sys.stderr)
        except (RuntimeError,ValueError) as error:print(str(error),file=sys.stderr)
    def ready():
        line=sys.stdin.readline()
        if not line:loop.remove_reader(sys.stdin.fileno());return
        task=asyncio.create_task(control(line));controls.add(task);task.add_done_callback(controls.discard)
    result = 1
    from contextlib import aclosing
    try:
        async with aclosing(agent.run(args.prompt)) as events:
            async for event in events:
                if args.interactive and not reader:
                    loop.add_reader(sys.stdin.fileno(),ready);reader=True
                    print('Controls: /steer TEXT, /cancel',file=sys.stderr)
                if args.json:
                    print(json.dumps({"event": event.kind, "data": event.data}, ensure_ascii=False), flush=True)
                elif event.kind == "text_delta": print(event.data["text"], end="", flush=True)
                elif event.kind == "tool_end": print(f"\n[{event.data['name']}: {event.data['status']}]", file=sys.stderr)
                elif event.kind == "error": print(event.data["message"], file=sys.stderr)
                if event.kind == "run_end": result = 0 if event.data["reason"] == "completed" else 130 if event.data['reason']=='cancelled' else 1
    finally:
        if reader:loop.remove_reader(sys.stdin.fileno())
        for task in controls:task.cancel()
        await asyncio.gather(*controls,return_exceptions=True)
    if not args.json: print()
    return result
