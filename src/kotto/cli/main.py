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
    args = parser.parse_args(argv)
    if args.command is None:
        parser.print_help()
        return 0

    if args.command == "chat":
        from kotto.cli.chat import chat
        try:
            settings = Settings.from_env(os.environ)
            if not args.prompt.strip():
                raise ConfigurationError("Prompt must not be empty.")
            return asyncio.run(chat(settings, args.prompt, json_mode=args.json))
        except ConfigurationError as error:
            if args.json:
                print(json.dumps({"event": "error", "data": {"kind": "configuration", "message": str(error), "complete": False}}))
            else:
                print(str(error))
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
