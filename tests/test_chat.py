import json
import os
import subprocess
import sys
import threading
import unittest
from contextlib import redirect_stdout, redirect_stderr
from io import StringIO
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from kotto.cli.chat import chat
from kotto.config import Settings
from kotto.contracts.event import ModelEvent
from kotto.model.gateway import ModelError


class ScriptedGateway:
    def __init__(self, fail=False):
        self.fail = fail

    async def stream(self, messages):
        yield ModelEvent("text_delta", {"text": "hello"})
        if self.fail:
            raise ModelError("network", "Connection interrupted")
        yield ModelEvent("message", {"role": "assistant", "content": "hello"})
        yield ModelEvent("finished", {"reason": "stop"})


class ChatTests(unittest.IsolatedAsyncioTestCase):
    async def test_plain_chat(self):
        with redirect_stdout(StringIO()) as out:
            result = await chat(None, "hi", gateway=ScriptedGateway())
        self.assertEqual(result, 0)
        self.assertEqual(out.getvalue(), "hello\n")

    async def test_json_failure_never_claims_completion(self):
        with redirect_stdout(StringIO()) as out:
            result = await chat(None, "hi", gateway=ScriptedGateway(True), json_mode=True)
        events = [json.loads(line) for line in out.getvalue().splitlines()]
        self.assertEqual(result, 1)
        self.assertFalse(events[-1]["data"]["complete"])
        self.assertNotIn("message", [event["event"] for event in events])

    async def test_plain_failure_is_on_stderr(self):
        with redirect_stdout(StringIO()) as out, redirect_stderr(StringIO()) as err:
            result = await chat(None, "hi", gateway=ScriptedGateway(True))
        self.assertEqual(result, 1)
        self.assertEqual(out.getvalue(), "hello\n")
        self.assertIn("incomplete", err.getvalue())

    async def test_missing_key_does_not_send_request(self):
        settings = Settings("https://example.invalid", "deepseek-flash", Path.cwd(), "")
        with redirect_stdout(StringIO()) as out:
            result = await chat(settings, "hi", json_mode=True)
        self.assertEqual(result, 2)
        self.assertEqual(json.loads(out.getvalue())["data"]["kind"], "configuration")


class ChatHTTPTests(unittest.TestCase):
    def test_real_cli_with_local_http_fixture(self):
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_POST(self):
                request = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                self.server.request_payload = request
                payload = {
                    "choices": [
                        {"index": 0, "delta": {"content": "本地夹具回复"}, "finish_reason": None}
                    ]
                }
                end = {"choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]}
                body = (
                    "data: "
                    + json.dumps(payload, ensure_ascii=False)
                    + "\n\ndata: "
                    + json.dumps(end)
                    + "\n\ndata: [DONE]\n\n"
                ).encode()
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            env = {
                k: v
                for k, v in os.environ.items()
                if not k.startswith("KOTTO_") and k != "DEEPSEEK_API_KEY"
            }
            env.update(
                PYTHONPATH=str(Path(__file__).resolve().parents[1] / "src"),
                KOTTO_API_KEY="fixture-secret",
                KOTTO_BASE_URL=f"http://127.0.0.1:{server.server_port}",
            )
            result = subprocess.run(
                [sys.executable, "-m", "kotto", "chat", "你好", "--json"],
                env=env,
                capture_output=True,
                text=True,
                timeout=5,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            events = [json.loads(line) for line in result.stdout.splitlines()]
            self.assertEqual(events[0]["data"]["text"], "本地夹具回复")
            self.assertEqual(events[-1]["event"], "finished")
            self.assertEqual(server.request_payload["messages"][0]["content"], "你好")
            self.assertNotIn("fixture-secret", result.stdout + result.stderr)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)
