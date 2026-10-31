"""DeepSeek wire protocol tests; all responses are explicit local fixtures."""

import asyncio
import json
import unittest
from pathlib import Path

import httpx

from kotto.config import Settings
from kotto.model.gateway import DeepSeekGateway, ModelError


def packet(delta=None, finish=None, usage=None):
    payload = {"choices": [{"index": 0, "delta": delta or {}, "finish_reason": finish}]}
    if usage is not None:
        payload["usage"] = usage
    return "data: " + json.dumps(payload, ensure_ascii=False) + "\n\n"


class ModelTests(unittest.IsolatedAsyncioTestCase):
    def settings(self, base="https://example.invalid"):
        return Settings(base, "deepseek-flash", Path.cwd(), "fixture-secret")

    async def collect(self, body, status=200):
        def handler(request):
            self.assertEqual(request.url.path, "/chat/completions")
            self.assertEqual(request.headers["authorization"], "Bearer fixture-secret")
            self.assertTrue(json.loads(request.content)["stream"])
            return httpx.Response(status, text=body, headers={"content-type": "text/event-stream"})
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            gateway = DeepSeekGateway(self.settings(), client=client)
            return [e async for e in gateway.stream([{"role": "user", "content": "hello"}])]

    async def test_text_reasoning_usage_and_finish(self):
        body = packet({"reasoning_content": "思考"}) + packet({"content": "你好"})
        body += packet(finish="stop") + 'data: {"choices": [], "usage": {"total_tokens": 9}}\n\n'
        events = await self.collect(body + "data: [DONE]\n\n")
        self.assertEqual([e.kind for e in events], ["reasoning_delta", "text_delta", "usage", "message", "finished"])
        self.assertEqual(events[-2].data["content"], "你好")
        self.assertEqual(events[-2].data["reasoning_content"], "思考")
        self.assertEqual(events[-1].data["reason"], "stop")

    async def test_tool_parameters_are_complete_before_emission(self):
        body = packet({"tool_calls": [{"index": 0, "id": "c1", "type": "function", "function": {"name": "read", "arguments": '{"path":'}}]})
        body += packet({"tool_calls": [{"index": 0, "function": {"arguments": '"a.py"}'}}]})
        events = await self.collect(body + packet(finish="tool_calls") + "data: [DONE]\n\n")
        call = events[-2].data["tool_calls"][0]
        self.assertEqual(json.loads(call["function"]["arguments"]), {"path": "a.py"})
        self.assertEqual(call["id"], "c1")

    async def test_http_errors_are_safe_and_distinct(self):
        for status, kind in [(401, "authentication"), (429, "rate_limit"), (503, "server"), (400, "request")]:
            with self.subTest(status=status):
                with self.assertRaises(ModelError) as error:
                    await self.collect("fixture-secret private-error-body", status)
                self.assertEqual(error.exception.kind, kind)
                self.assertNotIn("fixture-secret", str(error.exception))
                self.assertNotIn("private-error-body", str(error.exception))

    async def test_interrupted_and_malformed_streams_fail(self):
        for body in [packet({"content": "partial"}), "data: broken\n\n", "data: []\n\n", packet(finish="stop"), "data: [DONE]\n\n"]:
            with self.subTest(body=body):
                with self.assertRaises(ModelError):
                    await self.collect(body)

    async def test_no_message_committed_before_done_marker(self):
        seen = []
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(200, text=packet({"content": "partial"}) + packet(finish="stop")))) as client:
            with self.assertRaises(ModelError):
                async for event in DeepSeekGateway(self.settings(), client=client).stream([{"role": "user", "content": "hi"}]):
                    seen.append(event.kind)
        self.assertNotIn("message", seen)
        self.assertNotIn("finished", seen)

    async def test_transport_timeout_and_disconnect_are_classified(self):
        for exception, kind in [(httpx.ConnectTimeout("fixture-secret"), "timeout"),
                                (httpx.ConnectError("fixture-secret"), "network")]:
            def handler(request):
                raise exception
            async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
                with self.assertRaises(ModelError) as error:
                    await anext(DeepSeekGateway(self.settings(), client=client).stream([{"role": "user", "content": "hi"}]))
                self.assertEqual(error.exception.kind, kind)
                self.assertNotIn("fixture-secret", str(error.exception))

    async def test_streaming_over_real_local_http_is_incremental(self):
        release = asyncio.Event()
        first = packet({"content": "早"}).encode()
        tail = (packet({"content": "晚"}) + packet(finish="stop") + "data: [DONE]\n\n").encode()

        async def serve(reader, writer):
            try:
                headers = await reader.readuntil(b"\r\n\r\n")
                for line in headers.split(b"\r\n"):
                    if line.lower().startswith(b"content-length:"):
                        await reader.readexactly(int(line.split(b":", 1)[1]))
                writer.write(f"HTTP/1.1 200 OK\r\nContent-Type: text/event-stream\r\nContent-Length: {len(first)+len(tail)}\r\nConnection: close\r\n\r\n".encode())
                # Split a multibyte UTF-8 sequence across network writes.
                index = first.index("早".encode()) + 1
                writer.write(first[:index]); await writer.drain()
                writer.write(first[index:]); await writer.drain()
                await release.wait()
                writer.write(tail); await writer.drain()
            finally:
                writer.close()
                await writer.wait_closed()

        server = await asyncio.start_server(serve, "127.0.0.1", 0)
        try:
            address = f"http://127.0.0.1:{server.sockets[0].getsockname()[1]}"
            async with httpx.AsyncClient(trust_env=False) as client:
                stream = DeepSeekGateway(self.settings(address), client=client).stream([{"role": "user", "content": "hi"}])
                first_event = await asyncio.wait_for(anext(stream), 2)
                self.assertEqual(first_event.data["text"], "早")
                self.assertFalse(release.is_set())
                release.set()
                rest = [e async for e in stream]
                self.assertEqual(rest[-2].data["content"], "早晚")
        finally:
            release.set()
            server.close()
            await server.wait_closed()
