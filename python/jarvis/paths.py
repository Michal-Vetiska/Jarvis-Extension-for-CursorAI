"""Application paths and data directory helpers."""

from __future__ import annotations

import os
from pathlib import Path


def expand(path: str | Path) -> Path:
    return Path(os.path.expanduser(str(path))).resolve()


def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def default_config_path() -> Path:
    return repo_root() / "config" / "default.toml"


def data_dir(configured: str | None = None) -> Path:
    raw = configured or "~/Library/Application Support/JARVIS"
    path = expand(raw)
    path.mkdir(parents=True, exist_ok=True)
    return path


def socket_path(data: Path | None = None, name: str = "jarvis.sock") -> Path:
    base = data or data_dir()
    return base / name


def db_path(data: Path | None = None) -> Path:
    base = data or data_dir()
    return base / "jarvis.db"


def log_dir(data: Path | None = None) -> Path:
    path = (data or data_dir()) / "logs"
    path.mkdir(parents=True, exist_ok=True)
    return path
