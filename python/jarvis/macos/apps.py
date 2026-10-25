"""macOS application and window helpers via AppleScript / NSWorkspace patterns."""

from __future__ import annotations

import json
import subprocess
from typing import Any


def _osascript(script: str, timeout: float = 15.0) -> str:
    result = subprocess.run(
        ["osascript", "-e", script],
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "AppleScript selhal")
    return result.stdout.strip()


def list_running_apps() -> list[dict[str, Any]]:
    script = """
    set output to ""
    tell application "System Events"
        set procs to (every process whose background only is false)
        repeat with p in procs
            set output to output & name of p & linefeed
        end repeat
    end tell
    return output
    """
    raw = _osascript(script)
    names = [line.strip() for line in raw.splitlines() if line.strip()]
    return [{"name": name} for name in names]


def open_application(name: str) -> dict[str, Any]:
    subprocess.run(["open", "-a", name], check=True)
    return {"opened": name, "verified": _is_running(name)}


def activate_application(name: str) -> dict[str, Any]:
    _osascript(f'tell application "{name}" to activate')
    return {"activated": name, "verified": _is_running(name)}


def quit_application(name: str) -> dict[str, Any]:
    _osascript(f'tell application "{name}" to quit')
    return {"quit": name, "still_running": _is_running(name)}


def _is_running(name: str) -> bool:
    try:
        apps = list_running_apps()
        return any(a["name"].lower() == name.lower() for a in apps)
    except Exception:  # noqa: BLE001
        return False


def list_windows() -> list[dict[str, Any]]:
    script = """
    set output to ""
    tell application "System Events"
        set procs to (every process whose background only is false)
        repeat with p in procs
            set appName to name of p
            try
                repeat with w in (windows of p)
                    set output to output & appName & "|||" & (name of w) & linefeed
                end repeat
            end try
        end repeat
    end tell
    return output
    """
    raw = _osascript(script)
    windows: list[dict[str, Any]] = []
    for line in raw.splitlines():
        if "|||" not in line:
            continue
        app, title = line.split("|||", 1)
        windows.append({"app": app.strip(), "title": title.strip()})
    return windows


def focus_window(app: str, title_contains: str | None = None) -> dict[str, Any]:
    if title_contains:
        script = f'''
        tell application "System Events"
            tell process "{app}"
                set frontmost to true
                repeat with w in windows
                    if name of w contains "{title_contains}" then
                        perform action "AXRaise" of w
                        return name of w
                    end if
                end repeat
            end tell
        end tell
        '''
    else:
        script = f'tell application "{app}" to activate'
    result = _osascript(script)
    return {"focused_app": app, "window": result or None, "verified": True}


def open_url(url: str) -> dict[str, Any]:
    subprocess.run(["open", url], check=True)
    return {"opened_url": url}


def open_file(path: str) -> dict[str, Any]:
    subprocess.run(["open", path], check=True)
    return {"opened_file": path}


def reveal_in_finder(path: str) -> dict[str, Any]:
    subprocess.run(["open", "-R", path], check=True)
    return {"revealed": path}


def send_keyboard_shortcut(key: str, modifiers: list[str] | None = None) -> dict[str, Any]:
    mods = modifiers or []
    using = ""
    mapping = {
        "command": "command down",
        "cmd": "command down",
        "shift": "shift down",
        "option": "option down",
        "alt": "option down",
        "control": "control down",
        "ctrl": "control down",
    }
    parts = [mapping[m.lower()] for m in mods if m.lower() in mapping]
    if parts:
        using = " using {" + ", ".join(parts) + "}"
    script = f'tell application "System Events" to keystroke "{key}"{using}'
    _osascript(script)
    return {"key": key, "modifiers": mods}


def type_text(text: str) -> dict[str, Any]:
    # Prefer clipboard paste for reliability with Unicode/Czech characters.
    encoded = json.dumps(text)
    script = f'''
    set the clipboard to {encoded}
    tell application "System Events" to keystroke "v" using command down
    '''
    _osascript(script)
    return {"typed_chars": len(text)}


def inspect_active_window() -> dict[str, Any]:
    script = '''
    tell application "System Events"
        set p to first application process whose frontmost is true
        set appName to name of p
        try
            set winName to name of window 1 of p
        on error
            set winName to ""
        end try
        return appName & "|||" & winName
    end tell
    '''
    raw = _osascript(script)
    app, title = (raw.split("|||", 1) + [""])[:2]
    return {"app": app.strip(), "title": title.strip()}


def permission_diagnostics() -> dict[str, Any]:
    """Best-effort permission checks (cannot grant them programmatically)."""
    accessibility = False
    try:
        list_running_apps()
        accessibility = True
    except Exception as exc:  # noqa: BLE001
        accessibility_error = str(exc)
    else:
        accessibility_error = None

    return {
        "accessibility": {"ok": accessibility, "error": accessibility_error},
        "microphone": {
            "ok": None,
            "note": "Ověř v Nastavení systému → Soukromí a zabezpečení → Mikrofon",
        },
        "automation": {
            "ok": accessibility,
            "note": "Automation dialogs se zobrazí při první kontrole System Events / Cursor",
        },
        "screen_recording": {
            "ok": None,
            "note": "Potřeba jen pro screenshot fallback",
        },
    }
