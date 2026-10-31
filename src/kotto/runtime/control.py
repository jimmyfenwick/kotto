"""Bounded event delivery and cooperative control for one Agent run."""

import asyncio
import math
from kotto.contracts.event import AgentEvent
from kotto.contracts.tool import ToolResult


class BudgetExceeded(RuntimeError):
    pass


class Controlled:
    def _init_control(self, timeout, max_tool_calls, max_tokens):
        if (
            type(timeout) not in {int, float}
            or not math.isfinite(timeout)
            or timeout <= 0
            or type(max_tool_calls) is not int
            or max_tool_calls < 1
            or (max_tokens is not None and (type(max_tokens) is not int or max_tokens < 1))
        ):
            raise ValueError("Run budgets must be positive and finite.")
        self.timeout, self.max_tool_calls, self.max_tokens = timeout, max_tool_calls, max_tokens
        self._task = None
        self._pending = []
        self.state = "idle"

    async def steer(self, message):
        if not self.running:
            raise RuntimeError("No active run to steer.")
        if not message.strip() or len(message) > 64000 or len(self._pending) >= 32:
            raise ValueError("Steering queue or message limit exceeded.")
        self._pending.append(message)

    async def cancel(self):
        if self._task and not self._task.done():
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)

    def _settle_pending(self, reason):
        pending = {}
        for message in self.messages:
            for call in message.get("tool_calls", []):
                pending[call["id"]] = call
            if message["role"] == "tool":
                pending.pop(message["tool_call_id"], None)
        for call in pending.values():
            status = "cancelled" if reason == "cancelled" else "error"
            result = ToolResult(
                call["id"],
                status,
                {
                    "error": f"Run ended: {reason}. Inspect actual state before any further action; partial effects are possible."
                },
            )
            self._message(result.message())
            if self.journal:
                self.journal.append("tool_result", {"call_id": call["id"], "status": status})

    async def run(self, prompt):
        if self.running:
            raise RuntimeError("Agent already has an active run.")
        if not prompt.strip():
            raise ValueError("Prompt must not be empty.")
        self.running = True
        self._pending = []
        self.usage, self.rounds, self.tool_calls = {}, 0, 0
        self.state = "running"
        queue = asyncio.Queue(maxsize=64)
        closing = False

        def terminal(reason, error=None):
            if closing:
                return
            if self.journal:
                try:
                    self.journal.append(
                        "run_end",
                        {
                            "reason": reason,
                            "usage": self.usage,
                            "rounds": self.rounds,
                            "tool_calls": self.tool_calls,
                        },
                    )
                except Exception:
                    reason = "failed"
                    error = {"kind": "persistence", "message": "Could not persist terminal state."}
            # Final state takes precedence over buffered progress during cancellation.
            while not queue.empty():
                queue.get_nowait()
            if error:
                queue.put_nowait(AgentEvent("error", error))
            queue.put_nowait(
                AgentEvent(
                    "run_end",
                    {
                        "reason": reason,
                        "usage": self.usage,
                        "rounds": self.rounds,
                        "tool_calls": self.tool_calls,
                    },
                )
            )

        async def produce():
            source = self._run(prompt)
            reason = None
            try:
                async with asyncio.timeout(self.timeout):
                    async for event in source:
                        if self.extensions:
                            await self.extensions.emit(event)
                        if event.kind == "run_start" and self.journal:
                            self.journal.append("run_start", event.data)
                        if event.kind == "run_end":
                            reason = event.data["reason"]
                            if reason != "completed":
                                self._settle_pending(reason)
                            event = AgentEvent(
                                "run_end",
                                dict(
                                    event.data,
                                    usage=self.usage,
                                    rounds=self.rounds,
                                    tool_calls=self.tool_calls,
                                ),
                            )
                            if self.journal:
                                self.journal.append("run_end", event.data)
                        if not closing:
                            await queue.put(event)
            except asyncio.CancelledError:
                reason = "cancelled"
            except (asyncio.TimeoutError, BudgetExceeded):
                reason = "budget_exhausted"
            except Exception as error:
                reason = "failed"
                terminal(
                    reason,
                    {
                        "kind": "runtime",
                        "message": f"Agent operation failed ({type(error).__name__}).",
                    },
                )
            finally:
                await source.aclose()
                if reason in {"cancelled", "budget_exhausted"}:
                    try:
                        self._settle_pending(reason)
                    except Exception:
                        reason = "failed"
                    terminal(reason)
                elif reason is None:
                    terminal(
                        "failed",
                        {"kind": "runtime", "message": "Agent exited without a terminal state."},
                    )

        self._task = asyncio.create_task(produce())
        try:
            while True:
                event = await queue.get()
                yield event
                if event.kind == "run_end":
                    break
        finally:
            closing = True
            if not self._task.done():
                self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)
            self._task = None
            self.running = False
            self.state = "idle"
