"""Versioned, single-writer POSIX journal and opaque artifact storage."""

import fcntl
import json
import os
import re
import uuid
from pathlib import Path


class SessionError(RuntimeError):
    pass


class Journal:
    def __init__(self, root: Path, session_id=None):
        self.session_id = session_id or uuid.uuid4().hex
        if not re.fullmatch(r"[a-f0-9]{32}", self.session_id):
            raise SessionError("Invalid session ID.")
        self.directory = root.expanduser().resolve() / self.session_id
        if self.directory.is_symlink():
            raise SessionError("Session directory cannot be a symlink.")
        if session_id is not None and not self.directory.is_dir():
            raise SessionError("Session not found.")
        self.directory.mkdir(parents=True, mode=0o700, exist_ok=True)
        self.lock = None
        self.tail_repaired = False
        try:
            self.lock = os.open(
                self.directory / "lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600
            )
            try:
                fcntl.flock(self.lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise SessionError("Session already has a writer.") from None
            self.logfile = self.directory / "events.jsonl"
            self.events = self._load()
        except BaseException:
            self.close()
            raise

    def _load(self):
        if not self.logfile.exists():
            return []
        if self.logfile.is_symlink():
            raise SessionError("Journal cannot be a symlink.")
        events, offset = [], 0
        data = self.logfile.read_bytes()
        lines = data.splitlines(keepends=True)
        for index, line in enumerate(lines):
            if not line.endswith(b"\n") and index == len(lines) - 1:
                with self.logfile.open("r+b") as file:
                    file.truncate(offset)
                    file.flush()
                    os.fsync(file.fileno())
                self.tail_repaired = True
                break
            try:
                event = json.loads(line)
                if (
                    event["version"] != 1
                    or event["seq"] != len(events) + 1
                    or not isinstance(event["data"], dict)
                ):
                    raise ValueError
                if not isinstance(event["kind"], str):
                    raise ValueError
            except (ValueError, KeyError, TypeError):
                raise SessionError("Corrupt or unsupported journal; refusing recovery.") from None
            events.append(event)
            offset += len(line)
        return events

    def append(self, kind, data):
        event = {"version": 1, "seq": len(self.events) + 1, "kind": kind, "data": data}
        payload = (json.dumps(event, ensure_ascii=False) + "\n").encode()
        fd = os.open(self.logfile, os.O_CREAT | os.O_APPEND | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
        try:
            view = memoryview(payload)
            while view:
                written = os.write(fd, view)
                if written <= 0:
                    raise OSError("Journal write failed.")
                view = view[written:]
            os.fsync(fd)
        finally:
            os.close(fd)
        self.events.append(event)

    def messages(self):
        return [e["data"] for e in self.events if e["kind"] == "message"]

    def uncertain(self):
        pending = {}
        for event in self.events:
            data = event["data"]
            if event["kind"] == "tool_intent":
                pending[data["call_id"]] = True
            elif event["kind"] == "tool_result":
                pending.pop(data["call_id"], None)
            elif event["kind"] == "message":
                for call in data.get("tool_calls", []):
                    pending[call["id"]] = True
                if data.get("role") == "tool":
                    pending.pop(data["tool_call_id"], None)
        return list(pending)

    def acknowledge_unknown(self):
        from kotto.contracts.tool import ToolResult

        for call_id in self.uncertain():
            result = ToolResult(
                call_id,
                "unknown",
                {
                    "error": "Human acknowledged uncertain execution. Do not replay; inspect actual state first."
                },
            )
            self.append("tool_result", {"call_id": call_id, "status": "unknown"})
            self.append("message", result.message())

    def artifact(self, text):
        folder = self.directory / "artifacts"
        folder.mkdir(mode=0o700, exist_ok=True)
        if folder.is_symlink():
            raise SessionError("Artifact directory cannot be a symlink.")
        artifact_id = uuid.uuid4().hex
        fd = os.open(folder / artifact_id, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(fd, "w") as file:
            file.write(text)
            file.flush()
            os.fsync(file.fileno())
        return artifact_id

    def read_artifact(self, artifact_id):
        if not re.fullmatch(r"[a-f0-9]{32}", artifact_id):
            raise SessionError("Invalid artifact ID.")
        folder = self.directory / "artifacts"
        path = folder / artifact_id
        if folder.is_symlink() or path.is_symlink():
            raise SessionError("Artifact symlinks are not allowed.")
        return path.read_text()

    def close(self):
        if self.lock is not None:
            os.close(self.lock)
            self.lock = None

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
