"""Optional screen capture via screencapture CLI (requires Screen Recording permission)."""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path
from typing import Any


def capture_screen_with_permission(output_path: str | None = None) -> dict[str, Any]:
    path = Path(output_path) if output_path else Path(tempfile.gettempdir()) / "jarvis-screen.png"
    path.parent.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        ["screencapture", "-x", str(path)],
        capture_output=True,
        text=True,
        check=False,
    )
    ok = result.returncode == 0 and path.exists() and path.stat().st_size > 0
    return {
        "ok": ok,
        "path": str(path) if ok else None,
        "error": None if ok else (result.stderr.strip() or "screencapture selhal — zkontroluj Screen Recording oprávnění"),
    }
