"""Typed tool registry."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from pydantic import BaseModel, ValidationError

from jarvis.tools.permissions import PermissionLevel, requires_confirmation


@dataclass
class ToolSpec:
    name: str
    description: str
    permission: PermissionLevel
    input_model: type[BaseModel]
    result_model: type[BaseModel] | None
    handler: Callable[[BaseModel], Any]
    error_types: list[str] = field(default_factory=list)


@dataclass
class ToolResult:
    ok: bool
    data: dict[str, Any] | None = None
    error: str | None = None
    needs_confirmation: bool = False
    permission: str | None = None


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, ToolSpec] = {}

    def register(self, spec: ToolSpec) -> None:
        self._tools[spec.name] = spec

    def get(self, name: str) -> ToolSpec | None:
        return self._tools.get(name)

    def list_tools(self) -> list[dict[str, Any]]:
        out = []
        for spec in self._tools.values():
            schema = spec.input_model.model_json_schema()
            out.append(
                {
                    "name": spec.name,
                    "description": spec.description,
                    "permission": spec.permission.value,
                    "requires_confirmation": requires_confirmation(spec.permission),
                    "input_schema": schema,
                    "error_types": spec.error_types,
                }
            )
        return out

    def openai_tools(self) -> list[dict[str, Any]]:
        tools = []
        for spec in self._tools.values():
            schema = spec.input_model.model_json_schema()
            tools.append(
                {
                    "type": "function",
                    "function": {
                        "name": spec.name,
                        "description": (
                            f"{spec.description} "
                            f"[permission={spec.permission.value}"
                            f"{'; confirmation required' if requires_confirmation(spec.permission) else ''}]"
                        ),
                        "parameters": schema,
                    },
                }
            )
        return tools

    def execute(self, name: str, arguments: dict[str, Any], *, confirmed: bool = False) -> ToolResult:
        spec = self._tools.get(name)
        if not spec:
            return ToolResult(ok=False, error=f"Neznámý nástroj: {name}")
        if requires_confirmation(spec.permission) and not confirmed:
            return ToolResult(
                ok=False,
                needs_confirmation=True,
                permission=spec.permission.value,
                error="Vyžadováno potvrzení uživatele",
                data={"tool": name, "arguments": arguments, "permission": spec.permission.value},
            )
        try:
            payload = spec.input_model.model_validate(arguments or {})
        except ValidationError as exc:
            return ToolResult(ok=False, error=f"Neplatné vstupy: {exc}")
        try:
            result = spec.handler(payload)
            if isinstance(result, BaseModel):
                data = result.model_dump()
            elif isinstance(result, dict):
                data = result
            else:
                data = {"result": result}
            return ToolResult(ok=True, data=data, permission=spec.permission.value)
        except Exception as exc:  # noqa: BLE001
            return ToolResult(ok=False, error=str(exc), permission=spec.permission.value)
