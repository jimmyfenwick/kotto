import json
import tempfile
import unittest
from pathlib import Path

from kotto.contracts.event import ModelEvent
from kotto.runtime.agent import Agent
from kotto.tools.executor import ToolExecutor


class ReaderModel:
    def __init__(self):
        self.turn = 0

    async def stream(self, messages, **kwargs):
        self.turn += 1
        if self.turn < 3:
            name, args = (
                ("search", {"query": "answer"}) if self.turn == 1 else ("read", {"path": "a.py"})
            )
            message = {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": str(self.turn),
                        "type": "function",
                        "function": {"name": name, "arguments": json.dumps(args)},
                    }
                ],
            }
        else:
            self.result = json.loads(messages[-1]["content"])
            message = {"role": "assistant", "content": "a.py:1 answer = 42"}
        yield ModelEvent("message", message)
        yield ModelEvent("finished", {"reason": "stop"})


class AgentTests(unittest.IsolatedAsyncioTestCase):
    async def test_search_read_answer(self):
        with tempfile.TemporaryDirectory() as directory:
            Path(directory, "a.py").write_text("answer = 42\n")
            model = ReaderModel()
            agent = Agent(model, ToolExecutor(Path(directory)))
            events = [e async for e in agent.run("Find answer")]
            self.assertEqual(events[-1].data["reason"], "completed")
            self.assertIn("42", model.result["content"]["text"])
            self.assertIn("a.py:1", agent.messages[-1]["content"])

    async def test_invalid_paths_and_arguments(self):
        with tempfile.TemporaryDirectory() as directory, tempfile.TemporaryDirectory() as outside:
            Path(outside, "secret").write_text("private")
            Path(directory, "link").symlink_to(outside, target_is_directory=True)
            executor = ToolExecutor(Path(directory))
            for path in ["../secret", "link/secret"]:
                result = await executor.execute("x", "read", {"path": path})
                self.assertEqual(result.status, "error")
                self.assertNotIn("private", str(result.content))
            result = await executor.execute("x", "read", {"path": "x", "start": True})
            self.assertEqual(result.status, "error")
            self.assertEqual((await executor.execute("x", "missing", {})).status, "error")

    async def test_round_budget_and_failed_tool(self):
        with tempfile.TemporaryDirectory() as directory:
            agent = Agent(ReaderModel(), ToolExecutor(Path(directory)), max_rounds=1)
            events = [e async for e in agent.run("test")]
            self.assertEqual(events[-1].data["reason"], "budget_exhausted")
            self.assertEqual(agent.messages[-1]["role"], "tool")
