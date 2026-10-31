"""CLI entry point; only implemented commands are advertised."""

import argparse
import asyncio
import json
import os
import math
from typing import Sequence

from kotto import __version__
from kotto.config import ConfigurationError, Settings


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="kotto", description="KOTTO · Python Agent Harness")
    parser.add_argument("--version", action="version", version=f"kotto {__version__}")
    parser.add_argument(
        "--credentials-file",
        help="Explicit owner-only JSON config outside workspace; environment variables take precedence",
    )
    commands = parser.add_subparsers(dest="command")
    doctor = commands.add_parser(
        "doctor", help="Check local configuration without contacting a model"
    )
    doctor.add_argument("--json", action="store_true", help="Output a machine-readable report")
    chat_parser = commands.add_parser(
        "chat", help="Send one prompt to DeepSeek and stream its reply"
    )
    chat_parser.add_argument("prompt", help="Prompt text (quote multi-word prompts)")
    chat_parser.add_argument("--json", action="store_true", help="Output JSON events, one per line")
    run_parser = commands.add_parser(
        "run", help="Run a coding agent in the configured workspace (read-only by default)"
    )
    run_parser.add_argument("prompt")
    run_parser.add_argument("--json", action="store_true")
    run_parser.add_argument("--max-rounds", type=int, default=12)
    run_parser.add_argument("--max-tool-calls", type=int, default=64)
    run_parser.add_argument(
        "--timeout", type=float, default=300, help="Total run timeout in seconds"
    )
    run_parser.add_argument(
        "--max-total-tokens",
        type=int,
        help="Stop after reported cumulative usage reaches this limit; not a hard remote billing cap",
    )
    run_parser.add_argument(
        "--interactive",
        action="store_true",
        help="Accept /steer TEXT and /cancel while running (TTY text mode)",
    )
    run_parser.add_argument(
        "--context-window",
        type=int,
        default=64000,
        help="Conservative byte-based input budget, not an exact tokenizer",
    )
    run_parser.add_argument("--context-reserve", type=int, default=4096)
    run_parser.add_argument(
        "--extension",
        action="append",
        default=[],
        help="Explicit trusted Python plugin path (full host privileges)",
    )
    run_parser.add_argument(
        "--skill", action="append", default=[], help="Explicit task guide file; applies to this run"
    )
    command_parser = commands.add_parser(
        "command", help="Invoke an explicitly enabled extension command"
    )
    command_parser.add_argument("name")
    command_parser.add_argument("text", nargs="?", default="")
    command_parser.add_argument("--extension", action="append", default=[])
    command_parser.add_argument("--json", action="store_true")
    from kotto.cli.sessions import DEFAULT_ROOT
    from kotto.session.store import SessionError

    run_parser.add_argument("--session-root", default=DEFAULT_ROOT)
    run_parser.add_argument("--session", help="Resume an existing session ID")
    run_parser.add_argument(
        "--allow-write", action="store_true", help="Authorize file create/patch tools for this run"
    )
    run_parser.add_argument(
        "--allow-shell",
        action="store_true",
        help="Authorize LOCAL HOST commands with full user permissions (not sandboxed)",
    )
    run_parser.add_argument(
        "--ask", action="store_true", help="Ask before non-read tools (interactive terminal only)"
    )
    run_parser.add_argument(
        "--acknowledge-unknown",
        action="store_true",
        help="After checking actual state, mark uncertain calls unknown without replay",
    )
    session_parser = commands.add_parser(
        "sessions", help="Inspect local history and artifacts without contacting a model"
    )
    session_parser.add_argument("action", choices=["list", "show", "artifact"])
    session_parser.add_argument("session_id", nargs="?")
    session_parser.add_argument("artifact_id", nargs="?")
    session_parser.add_argument("--session-root", default=DEFAULT_ROOT)
    args = parser.parse_args(argv)
    if args.command is None:
        parser.print_help()
        return 0
    if args.command == "sessions":
        from kotto.cli.sessions import sessions

        try:
            return sessions(args)
        except (SessionError, OSError) as error:
            print(
                str(error) if isinstance(error, SessionError) else "Session file operation failed."
            )
            return 2

    if args.command in {"chat", "run", "command"}:
        from kotto.cli.chat import chat
        from kotto.model.gateway import ModelError

        try:
            settings = Settings.from_env(os.environ, credentials_file=args.credentials_file)
            if args.command == "command":
                from kotto import create_agent

                async def invoke():
                    async with create_agent(settings, extensions=args.extension) as agent:
                        value = await agent.extensions.command(args.name, args.text)
                        print(
                            json.dumps({"result": value}, ensure_ascii=False)
                            if args.json
                            else str(value)
                        )
                        return 0

                return asyncio.run(invoke())
            if not args.prompt.strip():
                raise ConfigurationError("Prompt must not be empty.")
            if args.command == "run":
                from kotto.cli.run import run

                if args.max_rounds < 1:
                    raise ConfigurationError("max-rounds must be positive.")
                if (
                    args.max_tool_calls < 1
                    or not math.isfinite(args.timeout)
                    or args.timeout <= 0
                    or (args.max_total_tokens is not None and args.max_total_tokens < 1)
                ):
                    raise ConfigurationError("Run budgets must be positive.")
                if args.context_reserve < 0 or args.context_window <= args.context_reserve + 256:
                    raise ConfigurationError("Invalid context window or reserve.")
                return asyncio.run(run(settings, args))
            return asyncio.run(chat(settings, args.prompt, json_mode=args.json))
        except (ConfigurationError, SessionError, OSError, ModelError) as error:
            safe_message = (
                "Local file operation failed." if isinstance(error, OSError) else str(error)
            )
            if args.json:
                print(
                    json.dumps(
                        {
                            "event": "error",
                            "data": {
                                "kind": "configuration",
                                "message": safe_message,
                                "complete": False,
                            },
                        }
                    )
                )
            else:
                print(safe_message)
            return 2
        except KeyboardInterrupt:
            if args.json:
                print(
                    json.dumps({"event": "error", "data": {"kind": "cancelled", "complete": False}})
                )
            else:
                print("\nOperation cancelled.")
            return 130

    try:
        report = Settings.from_env(os.environ, credentials_file=args.credentials_file).readiness()
    except ConfigurationError as exc:
        report = {"ready": False, "remote_verified": False, "error": str(exc)}
    if args.json:
        print(json.dumps(report, ensure_ascii=False))
    else:
        print("KOTTO local configuration: " + ("ready" if report["ready"] else "not ready"))
        for name, ok in report.get("checks", {}).items():
            print(f"  {name}: {'ok' if ok else 'missing'}")
        if "error" in report:
            print("  " + report["error"])
        print("Remote authentication has not been verified. No network request was made.")
    return 0 if report["ready"] else 2
