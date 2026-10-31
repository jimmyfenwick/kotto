"""Public CLI acceptance tests; no real credentials or network required."""

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SECRET = "test-only-kotto-secret-do-not-print"


class CLITests(unittest.TestCase):
    def run_cli(self, *args, settings=None):
        env = {
            k: v
            for k, v in os.environ.items()
            if not k.startswith("KOTTO_") and k != "DEEPSEEK_API_KEY"
        }
        env["PYTHONPATH"] = str(ROOT / "src")
        env.update(settings or {})
        return subprocess.run(
            [sys.executable, "-m", "kotto", *args],
            env=env,
            capture_output=True,
            text=True,
            timeout=5,
        )

    def configured(self, workspace):
        return {"KOTTO_API_KEY": SECRET, "KOTTO_WORKSPACE": workspace}

    def test_help_and_version(self):
        result = self.run_cli()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("doctor", result.stdout)
        result = self.run_cli("--version")
        self.assertEqual(result.returncode, 0, result.stderr)
        from kotto import __version__

        self.assertEqual(result.stdout.strip(), "kotto " + __version__)

    def test_missing_key_is_not_ready(self):
        result = self.run_cli("doctor", "--json")
        self.assertEqual(result.returncode, 2, result.stderr)
        report = json.loads(result.stdout)
        self.assertFalse(report["ready"])
        self.assertFalse(report["remote_verified"])

    def test_configured_does_not_claim_remote_verification(self):
        with tempfile.TemporaryDirectory() as workspace:
            result = self.run_cli("doctor", "--json", settings=self.configured(workspace))
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        self.assertTrue(report["ready"])
        self.assertFalse(report["remote_verified"])
        self.assertEqual(report["model"], "deepseek-flash")
        self.assertNotIn(SECRET, result.stdout + result.stderr)

    def test_deepseek_key_fallback(self):
        result = self.run_cli("doctor", "--json", settings={"DEEPSEEK_API_KEY": SECRET})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn(SECRET, result.stdout + result.stderr)

    def test_invalid_url_never_echoes_secret(self):
        for address in [
            "https://user:" + SECRET + "@example.com",
            "file:///tmp/x",
            "https://example.com?key=" + SECRET,
            "https://example.com#token",
            "https://example.com:bad",
            "https://exa mple.com",
        ]:
            with self.subTest(address=address):
                result = self.run_cli("doctor", "--json", settings={"KOTTO_BASE_URL": address})
                self.assertEqual(result.returncode, 2, result.stderr)
                self.assertNotIn(SECRET, result.stdout + result.stderr)
                self.assertFalse(json.loads(result.stdout)["ready"])

    def test_workspace_must_exist(self):
        with tempfile.TemporaryDirectory() as workspace:
            result = self.run_cli(
                "doctor", "--json", settings=self.configured(workspace + "/missing")
            )
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn("workspace", result.stdout)

    def test_unknown_command_is_rejected(self):
        result = self.run_cli("unknown-command", "pretend to work")
        self.assertEqual(result.returncode, 2)

    def test_doctor_never_connects_and_settings_repr_hides_key(self):
        from kotto.cli.main import main
        from kotto.config import Settings

        settings = Settings.from_env({"KOTTO_API_KEY": SECRET})
        self.assertNotIn(SECRET, repr(settings))
        with (
            patch.dict(os.environ, {"KOTTO_API_KEY": SECRET}, clear=True),
            patch("socket.socket.connect", side_effect=AssertionError("Network forbidden")),
            redirect_stdout(StringIO()) as output,
        ):
            self.assertEqual(main(["doctor", "--json"]), 0)
        self.assertNotIn(SECRET, output.getvalue())


if __name__ == "__main__":
    unittest.main()
