"""Validated tool dispatch and bounded workspace operations."""
import asyncio
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from kotto.contracts.tool import ToolResult

MAX_FILE = 1024 * 1024
IGNORED = {".git", ".venv", "node_modules", ".kotto", "__pycache__"}


def schema(properties, required):
    return {"type": "object", "properties": properties, "required": required, "additionalProperties": False}


def validate(value, definition):
    types = {"object": dict, "string": str, "integer": int, "boolean": bool, "array": list}
    kind = definition.get("type")
    if kind not in types or type(value) is not types[kind]:
        raise ValueError("Tool parameter type mismatch.")
    if "enum" in definition and value not in definition["enum"]:
        raise ValueError("Tool parameter is outside allowed values.")
    if kind == "object":
        properties = definition.get("properties", {})
        if set(definition.get("required", [])) - value.keys():
            raise ValueError("Required tool parameter is missing.")
        if definition.get("additionalProperties") is False and value.keys() - properties.keys():
            raise ValueError("Unexpected tool parameter.")
        for key, item in value.items():
            if key in properties: validate(item, properties[key])
    if kind == "integer":
        if value < definition.get("minimum", value) or value > definition.get("maximum", value):
            raise ValueError("Tool parameter outside numeric bounds.")


@dataclass
class Tool:
    name: str
    description: str
    parameters: dict
    handler: Callable
    effect: str = "read"

    def definition(self):
        return {"type": "function", "function": {"name": self.name, "description": self.description, "parameters": self.parameters}}


class ToolExecutor:
    def __init__(self, workspace: Path):
        self.workspace = workspace.resolve()
        if not self.workspace.is_dir(): raise ValueError("Workspace must exist.")
        self.tools = {}
        path = {"type": "string"}
        number = {"type": "integer", "minimum": 1, "maximum": 2000}
        self.register(Tool("list", "List a workspace directory. No recursive scan.", schema({"path": path}, []), self._list))
        self.register(Tool("read", "Read UTF-8 source with exact line numbers. Maximum 200 lines per call.", schema({"path": path, "start": number, "limit": number}, ["path"]), self._read))
        self.register(Tool("search", "Find literal text in at most 1000 source files; returns paths and line numbers.", schema({"query": {"type": "string"}}, ["query"]), self._search))

    def register(self, tool):
        if tool.name in self.tools: raise ValueError("Duplicate tool name.")
        self.tools[tool.name] = tool

    def definitions(self): return [tool.definition() for tool in self.tools.values()]

    def path(self, relative):
        raw = Path(relative)
        if raw.is_absolute() or ".." in raw.parts: raise ValueError("Path must be relative to workspace.")
        result = (self.workspace / raw).resolve()
        if not result.is_relative_to(self.workspace): raise ValueError("Path escapes workspace.")
        parts = result.relative_to(self.workspace).parts
        if any(p in IGNORED or p.startswith(".env") or p == "credentials.json" for p in parts):
            raise ValueError("Internal or credential path is not available to tools.")
        return result

    def _text(self, path):
        if not path.is_file(): raise ValueError("Not a regular file.")
        with path.open("rb") as handle: data = handle.read(MAX_FILE + 1)
        if len(data) > MAX_FILE: raise ValueError("File exceeds 1 MiB; use a smaller file.")
        if b"\0" in data: raise ValueError("Binary file is not supported.")
        return data.decode("utf-8")

    async def execute(self, call_id, name, args):
        try:
            if name not in self.tools: raise ValueError("Unknown tool.")
            tool = self.tools[name]
            validate(args, tool.parameters)
            return ToolResult(call_id, "ok", await tool.handler(args))
        except (ValueError, OSError, UnicodeError) as error:
            # OS errors can contain private absolute paths; return a safe category.
            message = str(error) if isinstance(error, ValueError) and not isinstance(error, UnicodeError) else "File operation failed."
            return ToolResult(call_id, "error", {"error": message})

    async def _list(self, args):
        def work():
            directory = self.path(args.get("path", "."))
            entries = []
            for p in sorted(directory.iterdir()):
                if p.is_symlink() or p.name in IGNORED or p.name.startswith(".env") or p.name == "credentials.json": continue
                entries.append({"path": str(p.relative_to(self.workspace)), "directory": p.is_dir()})
                if len(entries) >= 200: return {"entries": entries, "truncated": True}
            return {"entries": entries, "truncated": False}
        return await asyncio.to_thread(work)

    async def _read(self, args):
        def work():
            p = self.path(args["path"])
            lines = self._text(p).splitlines()
            start, limit = args.get("start", 1), min(args.get("limit", 200), 200)
            chosen = lines[start-1:start-1+limit]
            return {"path": str(p.relative_to(self.workspace)), "start": start,
                    "text": "\n".join(f"{i}: {line}" for i, line in enumerate(chosen, start)),
                    "total_lines": len(lines), "truncated": start-1+len(chosen) < len(lines)}
        return await asyncio.to_thread(work)

    async def _search(self, args):
        def work():
            if not args["query"]: raise ValueError("Search query must not be empty.")
            hits, scanned, skipped = [], 0, 0
            for base, dirs, files in os.walk(self.workspace, followlinks=False):
                dirs[:] = sorted(d for d in dirs if d not in IGNORED and not Path(base, d).is_symlink())
                for filename in sorted(files):
                    if filename.startswith(".env") or filename == "credentials.json": continue
                    p = Path(base, filename)
                    if p.is_symlink(): continue
                    scanned += 1
                    if scanned > 1000: return {"hits": hits, "truncated": True, "skipped": skipped}
                    try: lines = self._text(p).splitlines()
                    except (ValueError, OSError, UnicodeError):
                        skipped += 1
                        continue
                    for i, line in enumerate(lines, 1):
                        if args["query"] in line:
                            hits.append({"path": str(p.relative_to(self.workspace)), "line": i, "text": line[:500]})
                            if len(hits) >= 100: return {"hits": hits, "truncated": True, "skipped": skipped}
            return {"hits": hits, "truncated": False, "skipped": skipped}
        return await asyncio.to_thread(work)
