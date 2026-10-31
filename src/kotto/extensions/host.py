"""Explicitly enabled trusted Python extensions; not isolated plugins."""

import importlib.util
import inspect
import re
import sys
import uuid
from pathlib import Path
from kotto.model.gateway import ModelError


class ExtensionError(ModelError):
    def __init__(self, message):
        super().__init__("extension", message)


class ExtensionHost:
    def __init__(self, tools):
        self._tools = tools
        self._commands = {}
        self._listeners = []
        self._cleanup = []
        self._modules = []

    def register_tool(self, tool):
        self._tools.register(tool)

    def register_command(self, name, callback):
        if (
            not re.fullmatch(r"[a-z][a-z0-9_-]{0,63}", name)
            or name in {"run", "chat", "doctor", "sessions", "command"}
            or name in self._commands
            or not callable(callback)
        ):
            raise ExtensionError("Invalid, reserved or duplicate command name.")
        self._commands[name] = callback

    def subscribe(self, callback):
        if not callable(callback):
            raise ExtensionError("Event subscriber must be callable.")
        self._listeners.append(callback)

    async def emit(self, event):
        for callback in self._listeners:
            try:
                value = callback(event)
                if inspect.isawaitable(value):
                    await value
            except Exception:
                raise ExtensionError("Extension event subscriber failed.") from None

    async def command(self, name, text):
        if name not in self._commands:
            raise ExtensionError("Unknown extension command.")
        try:
            value = self._commands[name](text)
            return await value if inspect.isawaitable(value) else value
        except Exception:
            raise ExtensionError("Extension command failed.") from None

    def load(self, path):
        path = Path(path).expanduser().resolve()
        if not path.is_file() or path.suffix != ".py":
            raise ExtensionError("Explicit extension must be a Python file.")
        name = "_kotto_extension_" + uuid.uuid4().hex
        spec = importlib.util.spec_from_file_location(name, path)
        if not spec or not spec.loader:
            raise ExtensionError("Extension could not be loaded.")
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        self._modules.append(name)
        try:
            spec.loader.exec_module(module)
            cleanup = module.activate(self)
            if inspect.isawaitable(cleanup):
                if inspect.iscoroutine(cleanup):
                    cleanup.close()
                raise TypeError("Activation must be synchronous.")
            if cleanup is not None:
                if not callable(cleanup):
                    raise TypeError("Cleanup must be callable.")
                self._cleanup.append(cleanup)
        except Exception:
            raise ExtensionError("Extension activation failed. No Agent run was started.") from None

    def close(self):
        failed = False
        for callback in reversed(self._cleanup):
            try:
                callback()
            except Exception:
                failed = True
        self._cleanup.clear()
        for name in self._modules:
            sys.modules.pop(name, None)
        self._modules.clear()
        self._listeners.clear()
        if failed:
            raise ExtensionError("Extension cleanup failed.")


def load_skill(path):
    path = Path(path).expanduser().resolve()
    try:
        if not path.is_file() or path.stat().st_size > 64000:
            raise ValueError
        text = path.read_text()
        if not text.strip():
            raise ValueError
    except (ValueError, OSError, UnicodeError):
        raise ExtensionError("Skill file is missing, empty, oversized or unreadable.") from None
    return f"Explicitly enabled guide {path.name}; scope: this run.\n{text}"
