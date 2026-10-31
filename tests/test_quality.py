import math
import tempfile
import unittest
from pathlib import Path
from kotto import Agent, Journal, ToolExecutor
from kotto.session.store import SessionError
from test_control import SlowModel


class QualityTests(unittest.TestCase):
    def test_external_credentials_file_is_opt_in_and_outside_workspace(self):
        import json
        import os
        from kotto import Settings
        from kotto.config import ConfigurationError

        with tempfile.TemporaryDirectory() as root, tempfile.TemporaryDirectory() as outside:
            path = Path(outside, "credentials.json")
            path.write_text(json.dumps({"DEEPSEEK_API_KEY": "fixture-secret"}))
            os.chmod(path, 0o600)
            env = {"KOTTO_WORKSPACE": root}
            self.assertEqual(Settings.from_env(env).api_key, "")
            configured = Settings.from_env(env, credentials_file=path)
            self.assertEqual(configured.api_key, "fixture-secret")
            self.assertNotIn("fixture-secret", repr(configured))
            self.assertEqual(
                Settings.from_env(
                    dict(env, KOTTO_API_KEY="override"), credentials_file=path
                ).api_key,
                "override",
            )
            os.chmod(path, 0o644)
            with self.assertRaises(ConfigurationError):
                Settings.from_env(env, credentials_file=path)
            inside = Path(root, "credentials.json")
            inside.write_text("{}")
            os.chmod(inside, 0o600)
            with self.assertRaises(ConfigurationError):
                Settings.from_env(env, credentials_file=inside)

    def test_reused_provider_call_id_remains_uncertain(self):
        with tempfile.TemporaryDirectory() as root:
            with Journal(Path(root)) as store:
                message = {"role": "assistant", "content": None, "tool_calls": [{"id": "call_0"}]}
                store.append("message", message)
                store.append("tool_intent", {"call_id": "call_0"})
                store.append("message", {"role": "tool", "tool_call_id": "call_0", "content": "ok"})
                store.append("tool_result", {"call_id": "call_0", "status": "ok"})
                store.append("message", message)
                self.assertEqual(store.uncertain(), ["call_0"])

    def test_session_symlink_is_rejected(self):
        with tempfile.TemporaryDirectory() as root, tempfile.TemporaryDirectory() as outside:
            session_id = "a" * 32
            Path(root, session_id).symlink_to(outside, target_is_directory=True)
            with self.assertRaises(SessionError):
                Journal(Path(root), session_id)

    def test_nonfinite_budget_is_rejected(self):
        with tempfile.TemporaryDirectory() as root:
            for timeout in [math.nan, math.inf, -math.inf]:
                with self.assertRaises(ValueError):
                    Agent(SlowModel(), ToolExecutor(Path(root)), timeout=timeout)


class QualityAsyncTests(unittest.IsolatedAsyncioTestCase):
    async def test_sdk_resume_binds_workspace_and_original_permissions(self):
        from kotto import Policy
        from test_extension import FakeModel

        with (
            tempfile.TemporaryDirectory() as root,
            tempfile.TemporaryDirectory() as first,
            tempfile.TemporaryDirectory() as second,
        ):
            with Journal(Path(root)) as store:
                agent = Agent(FakeModel(), ToolExecutor(Path(first)), journal=store)
                await agent.aclose()
                with self.assertRaises(SessionError):
                    Agent(FakeModel(), ToolExecutor(Path(second)), journal=store)
                with self.assertRaises(SessionError):
                    Agent(
                        FakeModel(),
                        ToolExecutor(Path(first), policy=Policy(allow_write=True)),
                        journal=store,
                    )

    async def test_edit_waits_for_new_scoped_rules(self):
        from kotto import Policy
        from kotto.context.builder import ContextBuilder

        with tempfile.TemporaryDirectory() as root:
            workspace = Path(root)
            (workspace / "sub").mkdir()
            (workspace / "sub/AGENTS.md").write_text("Use reviewed project instructions.")
            tools = ToolExecutor(workspace, policy=Policy(allow_write=True))
            args = {"path": "sub/new.py", "text": "x=1\n"}
            self.assertEqual((await tools.execute("1", "write", args)).status, "error")
            self.assertFalse((workspace / "sub/new.py").exists())
            builder = ContextBuilder(workspace)
            await builder.build(
                [{"role": "system", "content": "base"}, {"role": "user", "content": "create file"}],
                [],
                paths=list(tools.observed_paths),
            )
            tools.reviewed_rules.update(builder.scope_digests)
            self.assertEqual((await tools.execute("2", "write", args)).status, "ok")

    async def test_run_boundaries_are_durable(self):
        from test_extension import FakeModel

        with tempfile.TemporaryDirectory() as root, tempfile.TemporaryDirectory() as workspace:
            with Journal(Path(root)) as store:
                agent = Agent(FakeModel(), ToolExecutor(Path(workspace)), journal=store)
                events = [e async for e in agent.run("test")]
                self.assertEqual(events[-1].data["reason"], "completed")
                kinds = [e["kind"] for e in store.events]
                self.assertIn("run_start", kinds)
                self.assertIn("run_end", kinds)
