"""CLI entry point; only implemented commands are advertised."""

import argparse
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
    args = parser.parse_args(argv)
    if args.command is None:
        parser.print_help()
        return 0

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
