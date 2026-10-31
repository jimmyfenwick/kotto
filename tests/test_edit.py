import hashlib
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path
from kotto.tools.executor import ToolExecutor
from kotto.tools.policy import Policy


class EditTests(unittest.IsolatedAsyncioTestCase):
    async def test_failed_atomic_replace_and_write_escape(self):
        with tempfile.TemporaryDirectory() as directory, tempfile.TemporaryDirectory() as outside:
            path = Path(directory, "a")
            path.write_text("old")
            Path(directory, "link").symlink_to(outside, target_is_directory=True)
            tools = ToolExecutor(Path(directory), policy=Policy(allow_write=True))
            args = {
                "path": "a",
                "old_text": "old",
                "new_text": "new",
                "expected_sha256": hashlib.sha256(b"old").hexdigest(),
            }
            with patch("kotto.tools.editing.os.replace", side_effect=OSError("fail")):
                self.assertEqual((await tools.execute("1", "patch", args)).status, "error")
            self.assertEqual(path.read_text(), "old")
            self.assertEqual(list(Path(directory).glob(".kotto-edit-*")), [])
            self.assertEqual(
                (await tools.execute("2", "write", {"path": "link/x", "text": "escape"})).status,
                "error",
            )
            self.assertFalse(Path(outside, "x").exists())

    async def test_readonly_and_conflict(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory, "a.py")
            path.write_text("value = 1\n")
            args = {
                "path": "a.py",
                "old_text": "1",
                "new_text": "2",
                "expected_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            }
            tools = ToolExecutor(Path(directory))
            self.assertEqual((await tools.execute("c", "patch", args)).status, "error")
            self.assertEqual(path.read_text(), "value = 1\n")
            tools.policy = Policy(allow_write=True)
            path.write_text("value = 1\n# user change\n")
            self.assertEqual((await tools.execute("c", "patch", args)).status, "error")
            self.assertIn("user change", path.read_text())

    async def test_create_patch_and_diff(self):
        with tempfile.TemporaryDirectory() as directory:
            tools = ToolExecutor(Path(directory), policy=Policy(allow_write=True))
            self.assertEqual(
                (await tools.execute("1", "write", {"path": "a.py", "text": "v = 1\n"})).status,
                "ok",
            )
            self.assertEqual(
                (await tools.execute("2", "write", {"path": "a.py", "text": "overwrite"})).status,
                "error",
            )
            read = await tools.execute("3", "read", {"path": "a.py"})
            result = await tools.execute(
                "4",
                "patch",
                {
                    "path": "a.py",
                    "old_text": "1",
                    "new_text": "2",
                    "expected_sha256": read.content["sha256"],
                },
            )
            self.assertEqual(result.status, "ok")
            self.assertIn("+v = 2", result.content["diff"])

    async def test_ask_is_explicit_and_unknown_effect_denied(self):
        seen = []

        async def approve(tool, args):
            seen.append(tool.name)
            return False

        with tempfile.TemporaryDirectory() as directory:
            tools = ToolExecutor(Path(directory), policy=Policy(approve=approve))
            result = await tools.execute("1", "write", {"path": "a", "text": "x"})
            self.assertEqual(result.status, "error")
            self.assertEqual(seen, ["write"])
            self.assertFalse(Path(directory, "a").exists())
