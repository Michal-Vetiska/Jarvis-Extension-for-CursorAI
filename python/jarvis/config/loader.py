"""Load and merge TOML configuration."""

from __future__ import annotations

import sys
from copy import deepcopy
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from jarvis.paths import data_dir, default_config_path, expand

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover
    import tomli as tomllib  # type: ignore


def _deep_merge(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    out = deepcopy(base)
    for key, value in overlay.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = deepcopy(value)
    return out


@dataclass
class AppConfig:
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def language(self) -> str:
        return str(self.raw.get("app", {}).get("language", "cs"))

    @property
    def data_directory(self) -> Path:
        return data_dir(self.raw.get("app", {}).get("data_dir"))

    @property
    def ipc_socket_name(self) -> str:
        return str(self.raw.get("ipc", {}).get("socket_name", "jarvis.sock"))

    @property
    def llm(self) -> dict[str, Any]:
        return dict(self.raw.get("llm", {}))

    @property
    def voice(self) -> dict[str, Any]:
        return dict(self.raw.get("voice", {}))

    @property
    def cursor(self) -> dict[str, Any]:
        return dict(self.raw.get("cursor", {}))

    @property
    def devserver(self) -> dict[str, Any]:
        return dict(self.raw.get("devserver", {}))

    @property
    def safety(self) -> dict[str, Any]:
        return dict(self.raw.get("safety", {}))


def load_toml(path: Path) -> dict[str, Any]:
    with path.open("rb") as fh:
        return tomllib.load(fh)


def load_config(path: Path | None = None, overrides: dict[str, Any] | None = None) -> AppConfig:
    cfg_path = path or default_config_path()
    raw: dict[str, Any] = {}
    if cfg_path.exists():
        raw = load_toml(cfg_path)
    user_cfg = expand("~/Library/Application Support/JARVIS/config.toml")
    if user_cfg.exists():
        raw = _deep_merge(raw, load_toml(user_cfg))
    if overrides:
        raw = _deep_merge(raw, overrides)
    return AppConfig(raw=raw)
