import asyncio
import tempfile
import unittest
import json
from pathlib import Path
from kotto.contracts.event import ModelEvent
from kotto.runtime.agent import Agent
from kotto.tools.executor import ToolExecutor


class SlowModel:
    def __init__(self):
        self.started = asyncio.Event()
        self.closed = asyncio.Event()

    async def stream(self, messages, **kwargs):
        self.started.set()
        try:
            await asyncio.sleep(20)
            yield ModelEvent("message", {"role": "assistant", "content": "done"})
        finally:
            self.closed.set()


class ControlTests(unittest.IsolatedAsyncioTestCase):
    async def test_tool_budget_settles_unexecuted_calls(self):
        class Model:
            async def stream(self, messages, **kwargs):
                yield ModelEvent(
                    "message",
                    {
                        "role": "assistant",
                        "content": None,
                        "tool_calls": [
                            {
                                "id": str(i),
                                "type": "function",
                                "function": {"name": "list", "arguments": "{}"},
                            }
                            for i in range(2)
                        ],
                    },
                )

        with tempfile.TemporaryDirectory() as directory:
            agent = Agent(Model(), ToolExecutor(Path(directory)), max_tool_calls=1)
            events = [e async for e in agent.run("limited")]
            self.assertEqual(events[-1].data["reason"], "budget_exhausted")
            results = [m for m in agent.messages if m["role"] == "tool"]
            self.assertEqual(len(results), 2)
            self.assertEqual(json.loads(results[-1]["content"])["status"], "error")

    async def test_cancel_and_concurrent_run(self):
        with tempfile.TemporaryDirectory() as directory:
            model = SlowModel()
            agent = Agent(model, ToolExecutor(Path(directory)))

            async def collect():
                return [e async for e in agent.run("first")]

            task = asyncio.create_task(collect())
            await model.started.wait()
            with self.assertRaises(RuntimeError):
                await anext(agent.run("second"))
            await agent.cancel()
            events = await task
            self.assertEqual(events[-1].data["reason"], "cancelled")
            self.assertTrue(model.closed.is_set())
            self.assertFalse(agent.running)

    async def test_consumer_close_and_total_timeout(self):
        with tempfile.TemporaryDirectory() as directory:
            model = SlowModel()
            agent = Agent(model, ToolExecutor(Path(directory)), timeout=0.05)
            events = [e async for e in agent.run("timeout")]
            self.assertEqual(events[-1].data["reason"], "budget_exhausted")
            self.assertTrue(model.closed.is_set())
            model = SlowModel()
            agent = Agent(model, ToolExecutor(Path(directory)))
            stream = agent.run("close")
            await anext(stream)
            await model.started.wait()
            await stream.aclose()
            self.assertTrue(model.closed.is_set())
            self.assertFalse(agent.running)

    async def test_steering_order_and_usage_budget(self):
        class Model:
            def __init__(self):
                self.start = asyncio.Event()
                self.release = asyncio.Event()
                self.requests = []

            async def stream(self, messages, **kwargs):
                self.requests.append(list(messages))
                self.start.set()
                if len(self.requests) == 1:
                    await self.release.wait()
                yield ModelEvent("usage", {"total_tokens": 10})
                yield ModelEvent("message", {"role": "assistant", "content": "ok"})

        with tempfile.TemporaryDirectory() as directory:
            model = Model()
            agent = Agent(model, ToolExecutor(Path(directory)))

            async def collect():
                return [e async for e in agent.run("start")]

            task = asyncio.create_task(collect())
            await model.start.wait()
            await agent.steer("one")
            await agent.steer("two")
            model.release.set()
            await task
            self.assertEqual(
                [m["content"] for m in model.requests[-1] if m["role"] == "user"],
                ["start", "one", "two"],
            )
            model = Model()
            model.release.set()
            agent = Agent(model, ToolExecutor(Path(directory)), max_tokens=5)
            events = [e async for e in agent.run("budget")]
            self.assertEqual(events[-1].data["reason"], "budget_exhausted")
