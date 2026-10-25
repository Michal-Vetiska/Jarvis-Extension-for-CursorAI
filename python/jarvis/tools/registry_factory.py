"""Build the full tool registry wired to runtime services."""

from __future__ import annotations

import subprocess
from typing import TYPE_CHECKING, Any

from jarvis.macos import accessibility, apps, screen
from jarvis.tools.base import ToolRegistry, ToolSpec
from jarvis.tools import models as m
from jarvis.tools.permissions import PermissionLevel

if TYPE_CHECKING:
    from jarvis.app_runtime import JarvisRuntime


def build_registry(runtime: "JarvisRuntime") -> ToolRegistry:
    reg = ToolRegistry()

    def add(name: str, description: str, permission: PermissionLevel, input_model, handler, errors=None):
        reg.register(
            ToolSpec(
                name=name,
                description=description,
                permission=permission,
                input_model=input_model,
                result_model=None,
                handler=handler,
                error_types=errors or [],
            )
        )

    add("list_running_apps", "Seznam běžících aplikací", PermissionLevel.READ_ONLY, m.EmptyInput, lambda _: {"apps": apps.list_running_apps()})
    add("open_application", "Otevře aplikaci", PermissionLevel.LOCAL_UI_ACTION, m.AppNameInput, lambda p: apps.open_application(p.name))
    add("activate_application", "Aktivuje aplikaci", PermissionLevel.LOCAL_UI_ACTION, m.AppNameInput, lambda p: apps.activate_application(p.name))
    add("quit_application", "Ukončí aplikaci", PermissionLevel.DESTRUCTIVE_ACTION, m.AppNameInput, lambda p: apps.quit_application(p.name))
    add("list_windows", "Seznam oken", PermissionLevel.READ_ONLY, m.EmptyInput, lambda _: {"windows": apps.list_windows()})
    add("focus_window", "Přepne fokus na okno", PermissionLevel.LOCAL_UI_ACTION, m.FocusWindowInput, lambda p: apps.focus_window(p.app, p.title_contains))
    add("open_file", "Otevře soubor", PermissionLevel.LOCAL_UI_ACTION, m.PathInput, lambda p: apps.open_file(p.path))
    add("reveal_in_finder", "Ukázat v Finderu", PermissionLevel.LOCAL_UI_ACTION, m.PathInput, lambda p: apps.reveal_in_finder(p.path))
    add("open_url", "Otevře URL v prohlížeči", PermissionLevel.EXTERNAL_ACTION, m.UrlInput, lambda p: apps.open_url(p.url))
    add("type_text", "Napíše text do aktivního okna", PermissionLevel.LOCAL_UI_ACTION, m.TypeTextInput, lambda p: apps.type_text(p.text))
    add("send_keyboard_shortcut", "Pošle klávesovou zkratku", PermissionLevel.LOCAL_UI_ACTION, m.ShortcutInput, lambda p: apps.send_keyboard_shortcut(p.key, p.modifiers))
    add("inspect_accessibility_tree", "Prohlédne AX strom", PermissionLevel.READ_ONLY, m.AccessibilityInspectInput, lambda p: accessibility.inspect_accessibility_tree(p.app, p.max_elements))
    add("click_accessibility_element", "Klikne na AX element", PermissionLevel.LOCAL_UI_ACTION, m.AccessibilityClickInput, lambda p: accessibility.click_accessibility_element(p.description_contains, p.app))
    add("capture_screen_with_permission", "Screenshot (vyžaduje Screen Recording)", PermissionLevel.READ_ONLY, m.CaptureScreenInput, lambda p: screen.capture_screen_with_permission(p.output_path))
    add("inspect_active_window", "Aktivní okno", PermissionLevel.READ_ONLY, m.EmptyInput, lambda _: apps.inspect_active_window())
    add("permission_diagnostics", "Diagnostika oprávnění", PermissionLevel.READ_ONLY, m.EmptyInput, lambda _: apps.permission_diagnostics())

    add(
        "register_project",
        "Zaregistruje alias projektu na existující složku",
        PermissionLevel.PROJECT_MODIFICATION,
        m.RegisterProjectInput,
        lambda p: runtime.register_project(p.alias, p.path),
    )
    add(
        "list_projects",
        "Seznam registrovaných projektů",
        PermissionLevel.READ_ONLY,
        m.EmptyInput,
        lambda _: {"projects": [proj.__dict__ for proj in runtime.db.list_projects()]},
    )
    add(
        "resolve_project",
        "Přeloží alias na cestu",
        PermissionLevel.READ_ONLY,
        m.ProjectAliasInput,
        lambda p: {"alias": p.alias, "path": runtime.db.resolve_project_path(p.alias)},
    )
    add(
        "open_project_in_cursor",
        "Otevře projekt v Cursoru",
        PermissionLevel.LOCAL_UI_ACTION,
        m.OpenProjectInCursorInput,
        lambda p: runtime.open_project_in_cursor(p.alias),
    )
    add(
        "cursor_status",
        "Stav instalace a autentizace Cursor Agent",
        PermissionLevel.READ_ONLY,
        m.EmptyInput,
        lambda _: runtime.cursor_status(),
    )
    add(
        "execute_coding_task",
        "Deleguje programátorský úkol na Cursor Agent CLI",
        PermissionLevel.PROJECT_MODIFICATION,
        m.ExecuteCodingTaskInput,
        lambda p: runtime.execute_coding_task(p.alias, p.instruction, p.timeout_seconds),
    )
    add(
        "inspect_git_changes",
        "Git status/diff projektu",
        PermissionLevel.READ_ONLY,
        m.ProjectAliasInput,
        lambda p: runtime.inspect_git(p.alias),
    )
    add(
        "run_validation_command",
        "Spustí schválený validační příkaz v projektu",
        PermissionLevel.PROCESS_EXECUTION,
        m.RunValidationInput,
        lambda p: runtime.run_validation(p.alias, p.command),
    )
    add(
        "detect_dev_server",
        "Detekuje vývojové skripty projektu",
        PermissionLevel.READ_ONLY,
        m.DetectDevServerInput,
        lambda p: runtime.detect_dev_server(p.alias),
    )
    add(
        "start_dev_server",
        "Spustí schválený vývojový server",
        PermissionLevel.PROCESS_EXECUTION,
        m.StartDevServerInput,
        lambda p: runtime.start_dev_server(p.alias, p.command, approve=p.approve),
    )
    add(
        "stop_dev_server",
        "Zastaví vývojový server projektu",
        PermissionLevel.PROCESS_EXECUTION,
        m.ServerAliasInput,
        lambda p: runtime.stop_dev_server(p.alias),
    )
    add(
        "dev_server_status",
        "Stav vývojových serverů",
        PermissionLevel.READ_ONLY,
        m.EmptyInput,
        lambda _: runtime.dev_server_status(),
    )
    add(
        "get_task_status",
        "Aktuální stav úkolu orchestrátoru",
        PermissionLevel.READ_ONLY,
        m.TaskIdInput,
        lambda p: runtime.get_task_status(p.task_id),
    )
    add(
        "cancel_task",
        "Zruší běžící úkol",
        PermissionLevel.PROCESS_EXECUTION,
        m.TaskIdInput,
        lambda p: runtime.cancel_task(p.task_id),
    )
    add(
        "run_autonomous_workflow",
        "Spustí multi-step workflow: Cursor úpravy + dev server + prohlížeč",
        PermissionLevel.PROJECT_MODIFICATION,
        m.ExecuteCodingTaskInput,
        lambda p: runtime.run_workflow(p.alias, p.instruction, timeout=p.timeout_seconds),
    )
    add(
        "speak",
        "Vysloví text česky",
        PermissionLevel.LOCAL_UI_ACTION,
        m.SpeakInput,
        lambda p: runtime.speak(p.text),
    )

    return reg


def run_shell_approved(command: str, cwd: str, timeout: float = 300.0) -> dict[str, Any]:
    result = subprocess.run(
        command,
        cwd=cwd,
        shell=True,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    return {
        "command": command,
        "cwd": cwd,
        "returncode": result.returncode,
        "stdout": (result.stdout or "")[-8000:],
        "stderr": (result.stderr or "")[-4000:],
        "ok": result.returncode == 0,
    }
