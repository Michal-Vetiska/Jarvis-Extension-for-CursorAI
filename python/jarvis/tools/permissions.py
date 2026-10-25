"""Permission levels for tool execution."""

from __future__ import annotations

from enum import Enum


class PermissionLevel(str, Enum):
    READ_ONLY = "READ_ONLY"
    LOCAL_UI_ACTION = "LOCAL_UI_ACTION"
    PROJECT_MODIFICATION = "PROJECT_MODIFICATION"
    PROCESS_EXECUTION = "PROCESS_EXECUTION"
    DESTRUCTIVE_ACTION = "DESTRUCTIVE_ACTION"
    EXTERNAL_ACTION = "EXTERNAL_ACTION"


CONFIRMATION_REQUIRED = {
    PermissionLevel.PROJECT_MODIFICATION,
    PermissionLevel.PROCESS_EXECUTION,
    PermissionLevel.DESTRUCTIVE_ACTION,
    PermissionLevel.EXTERNAL_ACTION,
}


def requires_confirmation(level: PermissionLevel | str) -> bool:
    if isinstance(level, str):
        level = PermissionLevel(level)
    return level in CONFIRMATION_REQUIRED
