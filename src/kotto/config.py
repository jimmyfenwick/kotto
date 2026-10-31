"""Local configuration only: loading and validation never contact a service."""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping
from urllib.parse import urlsplit
import json


class ConfigurationError(ValueError):
    """A safe, value-free configuration diagnostic."""


@dataclass(frozen=True)
class Settings:
    base_url: str
    model: str
    workspace: Path
    api_key: str = field(repr=False)

    @classmethod
    def from_env(cls, env: Mapping[str, str], *, credentials_file=None) -> "Settings":
        if credentials_file:
            try:
                path = Path(credentials_file).expanduser().resolve()
                workspace = Path(env.get("KOTTO_WORKSPACE", ".")).expanduser().resolve()
                if (
                    path.is_relative_to(workspace)
                    or path.stat().st_mode & 0o077
                    or path.stat().st_size > 16384
                ):
                    raise ValueError
                values = json.loads(path.read_text())
                allowed = {"KOTTO_API_KEY", "DEEPSEEK_API_KEY", "KOTTO_MODEL", "KOTTO_BASE_URL"}
                if (
                    not isinstance(values, dict)
                    or set(values) - allowed
                    or not all(isinstance(v, str) for v in values.values())
                ):
                    raise ValueError
                env = {**values, **env}
            except (OSError, ValueError, RuntimeError):
                raise ConfigurationError(
                    "Credentials file must be valid JSON, outside the workspace, owner-only readable, and contain supported string settings."
                ) from None
        base_url = env.get("KOTTO_BASE_URL", "https://api.deepseek.com").strip()
        try:
            parsed = urlsplit(base_url)
            invalid = (
                parsed.scheme not in {"http", "https"}
                or not parsed.hostname
                or parsed.username is not None
                or parsed.password is not None
                or "?" in base_url
                or "#" in base_url
                or any(c.isspace() or ord(c) < 32 for c in base_url)
            )
            parsed.port  # Validate malformed ports without exposing the original URL.
            if invalid:
                raise ValueError
        except ValueError:
            raise ConfigurationError(
                "KOTTO_BASE_URL must be an HTTP(S) URL without credentials, query, or fragment."
            ) from None

        model = env.get("KOTTO_MODEL", "deepseek-flash").strip()
        if not model or any(ord(c) < 32 for c in model):
            raise ConfigurationError("KOTTO_MODEL must be a non-empty model identifier.")
        api_key = env.get("KOTTO_API_KEY", env.get("DEEPSEEK_API_KEY", "")).strip()
        if any(ord(c) < 32 for c in api_key):
            raise ConfigurationError("API key contains invalid control characters.")
        try:
            workspace = Path(env.get("KOTTO_WORKSPACE", ".")).expanduser().resolve()
        except (OSError, RuntimeError, ValueError):
            raise ConfigurationError("KOTTO_WORKSPACE is not a valid path.") from None
        return cls(base_url.rstrip("/"), model, workspace, api_key)

    def readiness(self) -> dict:
        try:
            workspace_exists = self.workspace.is_dir()
        except OSError:
            workspace_exists = False
        return {
            "ready": bool(self.api_key) and workspace_exists,
            "remote_verified": False,
            "model": self.model,
            "checks": {
                "api_key_configured": bool(self.api_key),
                "workspace_exists": workspace_exists,
                "base_url_valid": True,
            },
        }
