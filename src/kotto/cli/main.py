"""CLI entry point; only implemented commands are advertised."""

import argparse
import asyncio
import json
import os
from typing import Sequence

from kotto import __version__
from kotto.config import ConfigurationError, Settings


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="kotto", description="KOTTO · Python Agent Harness")
    parser.add_argument("--version", action="version", version=f"kotto {__version__}")
    commands = parser.add_subparsers(dest="command")
    doctor = commands.add_parser("doctor", help="Check local configuration without contacting a model")
    doctor.add_argument("--json", action="store_true", help="Output a machine-readable report")
    chat_parser = commands.add_parser("chat", help="Send one prompt to DeepSeek and stream its reply")
    chat_parser.add_argument("prompt", help="Prompt text (quote multi-word prompts)")
    chat_parser.add_argument("--json", action="store_true", help="Output JSON events, one per line")
    run_parser = commands.add_parser("run", help="Run a read-only coding agent in the configured workspace")
    run_parser.add_argument("prompt")
    run_parser.add_argument("--json", action="store_true")
    run_parser.add_argument("--max-rounds", type=int, default=12)
    from kotto.cli.sessions import DEFAULT_ROOT
    from kotto.session.store import SessionError
    run_parser.add_argument("--session-root", default=DEFAULT_ROOT)
    run_parser.add_argument("--session", help="Resume an existing session ID")
    run_parser.add_argument("--allow-write", action="store_true", help="Authorize file create/patch tools for this run")
    run_parser.add_argument("--ask", action="store_true", help="Ask before non-read tools (interactive terminal only)")
    run_parser.add_argument("--acknowledge-unknown", action="store_true", help="After checking actual state, mark uncertain calls unknown without replay")
    session_parser = commands.add_parser("sessions", help="Inspect local history and artifacts without contacting a model")
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
        try: return sessions(args)
        except (SessionError, OSError) as error:
            print(str(error) if isinstance(error, SessionError) else "Session file operation failed.")
            return 2

    if args.command in {"chat", "run"}:
        from kotto.cli.chat import chat
        try:
            settings = Settings.from_env(os.environ)
            if not args.prompt.strip():
                raise ConfigurationError("Prompt must not be empty.")
            if args.command == "run":
                from kotto.cli.run import run
                if args.max_rounds < 1:
                    raise ConfigurationError("max-rounds must be positive.")
                return asyncio.run(run(settings, args))
            return asyncio.run(chat(settings, args.prompt, json_mode=args.json))
        except (ConfigurationError, SessionError, OSError) as error:
            safe_message = "Local file operation failed." if isinstance(error, OSError) else str(error)
            if args.json:
                print(json.dumps({"event": "error", "data": {"kind": "configuration", "message": safe_message, "complete": False}}))
            else:
                print(safe_message)
            return 2
        except KeyboardInterrupt:
            if args.json:
                print(json.dumps({"event": "error", "data": {"kind": "cancelled", "complete": False}}))
            else:
                print("\nChat cancelled.")
            return 130

    try:
        report = Settings.from_env(os.environ).readiness()
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
