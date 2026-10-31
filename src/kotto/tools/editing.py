"""Conflict-aware UTF-8 edits and atomic replacement, not a sandbox."""
import asyncio
import difflib
import hashlib
import os
import tempfile
from pathlib import Path
from kotto.tools.executor import MAX_FILE, Tool, schema


async def io_complete(function):
    task = asyncio.create_task(asyncio.to_thread(function))
    try: return await asyncio.shield(task)
    except asyncio.CancelledError:
        # A cancelled coroutine must not leave a background writer still running.
        await task
        raise


def register_edits(executor):
    string = {"type": "string"}
    async def create(args):
        def work():
            path = executor.path(args["path"])
            if len(args["text"].encode()) > MAX_FILE: raise ValueError("File exceeds 1 MiB.")
            if not path.parent.is_dir(): raise ValueError("Parent directory must exist.")
            return atomic(path, args["text"], None, create_only=True)
        return await io_complete(work)

    async def patch(args):
        def work():
            path = executor.path(args["path"])
            old = executor._text(path)
            expected = args["expected_sha256"]
            if hashlib.sha256(old.encode()).hexdigest() != expected: raise ValueError("Edit conflict: file changed since read.")
            if not args["old_text"] or old.count(args["old_text"]) != 1: raise ValueError("Replacement must match exactly once.")
            new = old.replace(args["old_text"], args["new_text"], 1)
            if len(new.encode()) > MAX_FILE: raise ValueError("File exceeds 1 MiB.")
            return atomic(path, new, (old, expected))
        return await io_complete(work)

    executor.register(Tool("write", "Create a NEW UTF-8 file; never overwrite. Parent directory must exist.", schema({"path": string, "text": string}, ["path", "text"]), create, "write"))
    executor.register(Tool("patch", "Replace one exact substring. Read first and pass its sha256 to detect conflicts.", schema({"path": string, "old_text": string, "new_text": string, "expected_sha256": string}, ["path", "old_text", "new_text", "expected_sha256"]), patch, "write"))


def atomic(path: Path, new, previous, create_only=False):
    fd, temporary = tempfile.mkstemp(prefix=".kotto-edit-", dir=path.parent)
    try:
        if previous: os.fchmod(fd, path.stat().st_mode & 0o777)
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as file:
            file.write(new); file.flush(); os.fsync(file.fileno())
        if create_only:
            # Hard-link creation fails atomically if the target already exists.
            os.link(temporary, path)
        else:
            if hashlib.sha256(path.read_bytes()).hexdigest() != previous[1]: raise ValueError("Edit conflict: file changed before replacement.")
            os.replace(temporary, path)
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try: os.fsync(directory_fd)
        finally: os.close(directory_fd)
    finally:
        Path(temporary).unlink(missing_ok=True)
    before = previous[0] if previous else ""
    diff = "".join(difflib.unified_diff(before.splitlines(keepends=True), new.splitlines(keepends=True), fromfile=path.name, tofile=path.name))
    return {"path": path.name, "diff": diff, "sha256": hashlib.sha256(new.encode()).hexdigest()}
