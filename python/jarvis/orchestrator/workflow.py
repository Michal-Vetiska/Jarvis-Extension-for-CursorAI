"""Stateful multi-step workflow engine."""

from __future__ import annotations

import logging
import threading
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable

# threading is used for cancel watchers inside run()

logger = logging.getLogger(__name__)


class StepStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    OK = "ok"
    FAILED = "failed"
    CANCELLED = "cancelled"
    SKIPPED = "skipped"


@dataclass
class Step:
    name: str
    run: Callable[["WorkflowContext"], dict[str, Any]]
    timeout: float = 600.0
    verification: Callable[[dict[str, Any]], bool] | None = None
    idempotent: bool = False
    status: StepStatus = StepStatus.PENDING
    inputs: dict[str, Any] = field(default_factory=dict)
    outputs: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    logs: list[str] = field(default_factory=list)


@dataclass
class WorkflowContext:
    task_id: str
    alias: str
    instruction: str
    data: dict[str, Any] = field(default_factory=dict)
    cancelled: bool = False

    def log(self, message: str) -> None:
        self.data.setdefault("_logs", []).append(message)


class WorkflowEngine:
    def __init__(self, on_update: Callable[[dict[str, Any]], None] | None = None) -> None:
        self.on_update = on_update
        self._current: dict[str, Any] | None = None
        self._lock = threading.Lock()
        self._cancel = threading.Event()

    @property
    def current(self) -> dict[str, Any] | None:
        with self._lock:
            return dict(self._current) if self._current else None

    def cancel(self) -> dict[str, Any]:
        self._cancel.set()
        with self._lock:
            if self._current:
                self._current["status"] = StepStatus.CANCELLED.value
                self._current["error"] = "Zrušeno uživatelem"
        return {"cancelled": True}

    def run(self, title: str, alias: str, instruction: str, steps: list[Step]) -> dict[str, Any]:
        self._cancel.clear()
        task_id = str(uuid.uuid4())
        ctx = WorkflowContext(task_id=task_id, alias=alias, instruction=instruction)
        state = {
            "task_id": task_id,
            "title": title,
            "alias": alias,
            "instruction": instruction,
            "status": "running",
            "current_step": None,
            "steps": [{"name": s.name, "status": s.status.value} for s in steps],
            "error": None,
            "result": {},
        }
        with self._lock:
            self._current = state
        self._emit(state)

        for idx, step in enumerate(steps):
            if self._cancel.is_set():
                step.status = StepStatus.CANCELLED
                state["status"] = "cancelled"
                state["error"] = "Zrušeno uživatelem"
                self._emit(state)
                return state

            step.status = StepStatus.RUNNING
            state["current_step"] = step.name
            state["steps"][idx]["status"] = step.status.value
            self._emit(state)
            started = time.time()
            try:
                # Expose cancel flag to step callbacks.
                def _watch_cancel() -> None:
                    while not self._cancel.is_set() and step.status == StepStatus.RUNNING:
                        time.sleep(0.05)
                    if self._cancel.is_set():
                        ctx.cancelled = True

                watcher = threading.Thread(target=_watch_cancel, daemon=True)
                watcher.start()
                outputs = step.run(ctx)
                if self._cancel.is_set() or ctx.cancelled:
                    step.status = StepStatus.CANCELLED
                    state["status"] = "cancelled"
                    state["error"] = "Zrušeno uživatelem"
                    state["steps"][idx]["status"] = step.status.value
                    self._emit(state)
                    return state
                if step.verification and not step.verification(outputs):
                    raise RuntimeError(f"Verifikace kroku {step.name} selhala")
                if time.time() - started > step.timeout:
                    raise TimeoutError(f"Timeout kroku {step.name}")
                step.outputs = outputs or {}
                step.status = StepStatus.OK
                state["steps"][idx]["status"] = step.status.value
                state["result"][step.name] = step.outputs
                self._emit(state)
            except Exception as exc:  # noqa: BLE001
                if self._cancel.is_set() or ctx.cancelled:
                    step.status = StepStatus.CANCELLED
                    state["status"] = "cancelled"
                    state["error"] = "Zrušeno uživatelem"
                    state["steps"][idx]["status"] = step.status.value
                    self._emit(state)
                    return state
                logger.exception("Step %s failed", step.name)
                step.status = StepStatus.FAILED
                step.error = str(exc)
                state["steps"][idx]["status"] = step.status.value
                state["status"] = "failed"
                state["error"] = str(exc)
                self._emit(state)
                return state

        if state["status"] == "running":
            state["status"] = "ok"
            state["current_step"] = None
        self._emit(state)
        return state

    def _emit(self, state: dict[str, Any]) -> None:
        with self._lock:
            self._current = dict(state)
        if self.on_update:
            self.on_update(dict(state))
