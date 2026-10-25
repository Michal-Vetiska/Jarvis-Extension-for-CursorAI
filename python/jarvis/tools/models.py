"""Pydantic input/output models for tools."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class EmptyInput(BaseModel):
    pass


class AppNameInput(BaseModel):
    name: str = Field(..., description="Název aplikace")


class FocusWindowInput(BaseModel):
    app: str
    title_contains: str | None = None


class PathInput(BaseModel):
    path: str


class UrlInput(BaseModel):
    url: str


class TypeTextInput(BaseModel):
    text: str


class ShortcutInput(BaseModel):
    key: str
    modifiers: list[str] = Field(default_factory=list)


class AccessibilityInspectInput(BaseModel):
    app: str | None = None
    max_elements: int = 40


class AccessibilityClickInput(BaseModel):
    description_contains: str
    app: str | None = None


class CaptureScreenInput(BaseModel):
    output_path: str | None = None


class RegisterProjectInput(BaseModel):
    alias: str
    path: str


class ProjectAliasInput(BaseModel):
    alias: str


class OpenProjectInCursorInput(BaseModel):
    alias: str


class ExecuteCodingTaskInput(BaseModel):
    alias: str
    instruction: str
    timeout_seconds: float | None = None


class RunValidationInput(BaseModel):
    alias: str
    command: str


class DetectDevServerInput(BaseModel):
    alias: str


class StartDevServerInput(BaseModel):
    alias: str
    command: str | None = None
    approve: bool = False


class ServerAliasInput(BaseModel):
    alias: str


class TaskIdInput(BaseModel):
    task_id: str | None = None


class ConfirmInput(BaseModel):
    confirmed: bool = True
    note: str | None = None


class SpeakInput(BaseModel):
    text: str


class GenericResult(BaseModel):
    data: dict[str, Any] = Field(default_factory=dict)
