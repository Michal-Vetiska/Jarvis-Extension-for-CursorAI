from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from jarvis.db import Database


def test_register_and_resolve_project():
    with tempfile.TemporaryDirectory() as tmp:
        project_dir = Path(tmp) / "XXWorkplace"
        project_dir.mkdir()
        db = Database(Path(tmp) / "test.db")
        project = db.register_project("XXWorkplace", str(project_dir))
        assert project.alias == "XXWorkplace"
        assert db.resolve_project_path("xxworkplace") == str(project_dir.resolve())


def test_register_missing_path_raises():
    with tempfile.TemporaryDirectory() as tmp:
        db = Database(Path(tmp) / "test.db")
        with pytest.raises(FileNotFoundError):
            db.register_project("Nope", str(Path(tmp) / "missing"))


def test_unknown_alias_raises():
    with tempfile.TemporaryDirectory() as tmp:
        db = Database(Path(tmp) / "test.db")
        with pytest.raises(KeyError):
            db.resolve_project_path("Ghost")
