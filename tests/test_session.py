import tempfile
import unittest
import os
import subprocess
import sys
from pathlib import Path
from kotto.session.store import Journal, SessionError


class SessionTests(unittest.TestCase):
    def test_process_exit_releases_lock(self):
        with tempfile.TemporaryDirectory() as root:
            code = "from pathlib import Path; from kotto.session.store import Journal; import os,sys; s=Journal(Path(sys.argv[1])); print(s.session_id,flush=True); s.append('tool_intent',{'call_id':'c1'}); os._exit(0)"
            process = subprocess.run(
                [sys.executable, "-c", code, root],
                env=os.environ.copy(),
                text=True,
                capture_output=True,
                check=True,
            )
            with Journal(Path(root), process.stdout.strip()) as store:
                self.assertEqual(store.uncertain(), ["c1"])

    def test_messages_and_artifacts_survive_reopen(self):
        with tempfile.TemporaryDirectory() as root:
            with Journal(Path(root)) as store:
                session_id = store.session_id
                store.append("message", {"role": "user", "content": "hello"})
                artifact = store.artifact("large result")
            with Journal(Path(root), session_id) as store:
                self.assertEqual(store.messages()[0]["content"], "hello")
                self.assertEqual(store.read_artifact(artifact), "large result")
                with self.assertRaises(SessionError):
                    store.read_artifact("../secret")

    def test_lock_and_unknown_execution(self):
        with tempfile.TemporaryDirectory() as root:
            with Journal(Path(root)) as store:
                with self.assertRaises(SessionError):
                    Journal(Path(root), store.session_id)
                store.append("tool_intent", {"call_id": "c1", "name": "shell"})
                session_id = store.session_id
            with Journal(Path(root), session_id) as store:
                self.assertEqual(store.uncertain(), ["c1"])
                self.assertEqual(len(store.events), 1)

    def test_tail_repair_and_middle_corruption(self):
        with tempfile.TemporaryDirectory() as root:
            with Journal(Path(root)) as store:
                session_id = store.session_id
                store.append("message", {"role": "user", "content": "ok"})
                logfile = store.directory / "events.jsonl"
            with logfile.open("ab") as file:
                file.write(b'{"broken":')
            with Journal(Path(root), session_id) as store:
                self.assertEqual(store.messages()[0]["content"], "ok")
                self.assertTrue(store.tail_repaired)
            logfile.write_text("broken\n{}\n")
            with self.assertRaises(SessionError):
                Journal(Path(root), session_id)


class SessionAgentTests(unittest.IsolatedAsyncioTestCase):
    async def test_journal_failure_prevents_tool_execution(self):
        from unittest.mock import patch
        from kotto.runtime.agent import Agent
        from kotto.tools.executor import ToolExecutor
        from test_agent import ReaderModel

        with tempfile.TemporaryDirectory() as root, tempfile.TemporaryDirectory() as workspace:
            with Journal(Path(root)) as store:
                tools = ToolExecutor(Path(workspace))
                agent = Agent(ReaderModel(), tools, journal=store)
                original = store.append

                def failing(kind, data):
                    if kind == "tool_intent":
                        raise OSError("disk failed")
                    return original(kind, data)

                with (
                    patch.object(store, "append", side_effect=failing),
                    patch.object(tools, "execute") as execute,
                ):
                    events = [event async for event in agent.run("test")]
                    self.assertEqual(events[-1].data["reason"], "failed")
                    execute.assert_not_called()

    async def test_resume_never_replays_uncertain_calls(self):
        from kotto.runtime.agent import Agent
        from kotto.tools.executor import ToolExecutor
        from test_agent import ReaderModel

        with tempfile.TemporaryDirectory() as root:
            with Journal(Path(root)) as store:
                store.append(
                    "message", {"role": "assistant", "content": None, "tool_calls": [{"id": "c1"}]}
                )
                store.append("tool_intent", {"call_id": "c1"})
                with self.assertRaises(SessionError):
                    Agent(ReaderModel(), ToolExecutor(Path(root)), journal=store)
                store.acknowledge_unknown()
                self.assertEqual(store.uncertain(), [])
                self.assertIn("unknown", store.messages()[-1]["content"])
