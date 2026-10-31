"""Explicit host execution with bounded capture and process-group cleanup."""
import asyncio
import os
import signal
from kotto.tools.executor import Tool, schema


async def terminate(process):
    try: os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError: pass
    try: await asyncio.wait_for(process.wait(), .5)
    except asyncio.TimeoutError: pass
    # The shell may exit before a descendant that ignores SIGTERM.
    try: os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError: pass
    await process.wait()


def register_shell(executor):
    async def shell(args):
        cwd = executor.path(args.get("cwd", "."))
        if not cwd.is_dir(): raise ValueError("Command directory must exist.")
        if not args['command'].strip(): raise ValueError("Command must not be empty.")
        env = {key: value for key, value in os.environ.items() if key not in {"KOTTO_API_KEY", "DEEPSEEK_API_KEY"}}
        process = await asyncio.create_subprocess_shell(args["command"], cwd=cwd, env=env,
            stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE, start_new_session=True)
        captured = {"stdout": bytearray(), "stderr": bytearray()}
        totals = {"stdout": 0, "stderr": 0}
        async def drain(reader, name):
            while chunk := await reader.read(8192):
                totals[name] += len(chunk)
                remaining = max(0, 512*1024-len(captured[name]))
                captured[name].extend(chunk[:remaining])
        readers = [asyncio.create_task(drain(process.stdout, "stdout")), asyncio.create_task(drain(process.stderr, "stderr"))]
        timed_out = False
        group = asyncio.gather(process.wait(), *readers)
        try:
            await asyncio.wait_for(asyncio.shield(group), args.get("timeout", 30))
        except asyncio.TimeoutError:
            timed_out = True
            await terminate(process)
        except BaseException:
            await terminate(process)
            raise
        finally:
            for task in readers:
                if not task.done(): task.cancel()
            await asyncio.gather(*readers, return_exceptions=True)
            await asyncio.gather(group, return_exceptions=True)
        result = {"returncode": process.returncode, "timed_out": timed_out, "truncated": False, "execution_host": "local"}
        for name, data in captured.items():
            result[name] = data[:6000].decode("utf-8", errors="replace")
            result[name+"_bytes"] = totals[name]
            if totals[name] > 6000:
                result['truncated'] = True
                result[name+"_artifact"] = executor.journal.artifact(data.decode("utf-8", errors="replace")) if executor.journal else None
                result[name+"_artifact_truncated"] = totals[name] > len(data)
        return result
    executor.register(Tool("shell", "Run a command on the LOCAL HOST with the user's full process permissions, NOT a sandbox. Output is bounded; nonzero returncode means command failed.", schema({"command": {"type": "string"}, "cwd": {"type": "string"}, "timeout": {"type": "integer", "minimum": 1, "maximum": 120}}, ["command"]), shell, "shell"))
