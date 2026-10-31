import json
import tempfile
import unittest
from pathlib import Path
from kotto.context.builder import ContextBuilder, ContextError


class ContextTests(unittest.IsolatedAsyncioTestCase):
    async def test_repeated_compaction_keeps_original_records(self):
        async def summarize(text):
            return "Decision: preserve API. Evidence a.py:1. Pending verification."

        with tempfile.TemporaryDirectory() as directory:
            builder = ContextBuilder(
                Path(directory), max_tokens=5000, reserve=200, summarizer=summarize
            )
            history = [
                {"role": "system", "content": "base"},
                {"role": "user", "content": "Keep the API unchanged."},
            ]
            for i in range(20):
                history.extend(
                    [
                        {"role": "assistant", "content": "x" * 800},
                        {"role": "user", "content": f"Continue {i}"},
                    ]
                )
                request = await builder.build(history, [])
                self.assertIn("Keep the API unchanged.", str(request))
            self.assertEqual(len(history), 42)
            self.assertTrue(builder.summary)

    async def test_rules_are_scoped_and_symlinks_rejected(self):
        with tempfile.TemporaryDirectory() as directory, tempfile.TemporaryDirectory() as outside:
            root = Path(directory)
            (root / "sub").mkdir()
            (root / "other").mkdir()
            (root / "AGENTS.md").write_text("ROOT_RULE")
            (root / "sub/AGENTS.md").write_text("SUB_RULE")
            (root / "other/AGENTS.md").write_text("OTHER_RULE")
            builder = ContextBuilder(root)
            result = await builder.build(
                [{"role": "system", "content": "base"}, {"role": "user", "content": "inspect"}],
                [],
                paths=["sub/a.py"],
            )
            self.assertIn("ROOT_RULE", result[0]["content"])
            self.assertIn("SUB_RULE", result[0]["content"])
            self.assertNotIn("OTHER_RULE", result[0]["content"])
            result = await builder.build(
                [{"role": "system", "content": "base"}, {"role": "user", "content": "inspect"}],
                [],
                paths=["other/a.py"],
            )
            self.assertNotIn("SUB_RULE", result[0]["content"])
            (root / "sub/AGENTS.md").unlink()
            (root / "sub/AGENTS.md").symlink_to(Path(outside, "AGENTS.md"))
            with self.assertRaises(ContextError):
                await builder.build([{"role": "system", "content": "base"}], [], paths=["sub/a.py"])

    async def test_compaction_preserves_requirements_and_tool_pairs(self):
        async def summarize(text):
            return "Decision: keep answer=42. Evidence a.py:1. Pending: verify."

        with tempfile.TemporaryDirectory() as directory:
            history = [
                {"role": "system", "content": "base"},
                {"role": "user", "content": "NEVER remove user files."},
            ]
            for i in range(8):
                history.extend(
                    [
                        {"role": "assistant", "content": "x" * 800, "tool_calls": [{"id": str(i)}]},
                        {"role": "tool", "tool_call_id": str(i), "content": "y" * 500},
                    ]
                )
            history.append({"role": "user", "content": "Continue and verify."})
            original = json.dumps(history)
            builder = ContextBuilder(
                Path(directory), max_tokens=5000, reserve=200, summarizer=summarize
            )
            request = await builder.build(history, [])
            self.assertIn("NEVER remove user files.", str(request))
            self.assertIn("a.py:1", str(request))
            self.assertEqual(json.dumps(history), original)
            seen = set()
            for message in request:
                for call in message.get("tool_calls", []):
                    seen.add(call["id"])
                if message["role"] == "tool":
                    self.assertIn(message["tool_call_id"], seen)

    async def test_failure_or_mandatory_overflow_preserves_history(self):
        async def fail(text):
            raise RuntimeError("summary failed")

        with tempfile.TemporaryDirectory() as directory:
            builder = ContextBuilder(Path(directory), max_tokens=2000, reserve=100, summarizer=fail)
            with self.assertRaises(ContextError):
                await builder.build(
                    [{"role": "system", "content": "s"}, {"role": "user", "content": "u" * 3000}],
                    [],
                )
            history = [{"role": "system", "content": "s"}, {"role": "user", "content": "keep"}] + [
                {"role": "assistant", "content": "x" * 800} for _ in range(10)
            ]
            with self.assertRaises(ContextError):
                await builder.build(history, [])
            self.assertEqual(builder.summary, "")
            self.assertEqual(len(history), 12)
