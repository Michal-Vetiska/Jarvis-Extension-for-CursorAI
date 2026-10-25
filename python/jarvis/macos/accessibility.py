"""Accessibility tree inspection via AppleScript System Events (best-effort)."""

from __future__ import annotations

import subprocess
from typing import Any


def _osascript(script: str) -> str:
    result = subprocess.run(
        ["osascript", "-e", script],
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "Accessibility AppleScript selhal")
    return result.stdout.strip()


def inspect_accessibility_tree(app: str | None = None, max_elements: int = 40) -> dict[str, Any]:
    target = app or ""
    script = f'''
    tell application "System Events"
        if "{target}" is "" then
            set p to first application process whose frontmost is true
        else
            set p to first application process whose name is "{target}"
        end if
        set appName to name of p
        set lines to {{}}
        try
            set uiElems to entire contents of window 1 of p
            set i to 0
            repeat with e in uiElems
                set i to i + 1
                if i > {max_elements} then exit repeat
                try
                    set roleName to role of e
                on error
                    set roleName to "?"
                end try
                try
                    set desc to description of e
                on error
                    try
                        set desc to name of e
                    on error
                        set desc to ""
                    end try
                end try
                set end of lines to (roleName & " :: " & desc)
            end repeat
        end try
        set AppleScript's text item delimiters to linefeed
        set joined to lines as text
        set AppleScript's text item delimiters to ""
        return appName & "|||" & joined
    end tell
    '''
    raw = _osascript(script)
    app_name, body = (raw.split("|||", 1) + [""])[:2]
    elements = []
    for line in body.splitlines():
        if " :: " in line:
            role, desc = line.split(" :: ", 1)
            elements.append({"role": role.strip(), "description": desc.strip()})
    return {"app": app_name.strip(), "elements": elements, "count": len(elements)}


def click_accessibility_element(description_contains: str, app: str | None = None) -> dict[str, Any]:
    target = app or ""
    needle = description_contains.replace('"', '\\"')
    script = f'''
    tell application "System Events"
        if "{target}" is "" then
            set p to first application process whose frontmost is true
        else
            set p to first application process whose name is "{target}"
        end if
        set uiElems to entire contents of window 1 of p
        repeat with e in uiElems
            try
                set desc to description of e
            on error
                try
                    set desc to name of e
                on error
                    set desc to ""
                end try
            end try
            if desc contains "{needle}" then
                try
                    click e
                    return "clicked:" & desc
                end try
            end if
        end repeat
        error "Element nenalezen"
    end tell
    '''
    result = _osascript(script)
    return {"result": result, "verified": result.startswith("clicked:")}
