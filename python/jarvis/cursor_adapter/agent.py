"""Cursor Agent CLI adapter (login-based, no API key required)."""

from __future__ import annotations

import json
import logging
import os
import shutil
import signal
import subprocess
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

logger = logging.getLogger(__name__)


@dataclass
class AgentRun:
    id: str
    workspace: str
    prompt: str
    status: str = "pending"
    pid: int | None = None
    output: str = ""
    error: str | None = None
    started_at: float | None = None
    finished_at: float | None = None
    process: subprocess.Popen[str] | None = field(default=None, repr=False)


class CursorAgentAdapter:
    def __init__(
        self,
        agent_bin: str = "agent",
        cursor_bin: str = "cursor",
        path_hint: str = "~/.local/bin",
        force: bool = True,
        trust: bool = True,
        output_format: str = "stream-json",
        default_timeout: float = 900.0,
    ) -> None:
        self.agent_bin = agent_bin
        self.cursor_bin = cursor_bin
        self.path_hint = path_hint
        self.force = force
        self.trust = trust
        self.output_format = output_format
        self.default_timeout = default_timeout
        self._runs: dict[str, AgentRun] = {}
        self._lock = threading.Lock()

    def _env(self) -> dict[str, str]:
        env = os.environ.copy()
        hint = str(Path(self.path_hint).expanduser())
        path = env.get("PATH", "")
        if hint not in path.split(":"):
            env["PATH"] = f"{hint}:{path}"
        return env

    def which_agent(self) -> str | None:
        return shutil.which(self.agent_bin, path=self._env()["PATH"])

    def which_cursor(self) -> str | None:
        return shutil.which(self.cursor_bin, path=self._env()["PATH"])

    def detect_installation(self) -> dict[str, Any]:
        cursor_path = self.which_cursor()
        agent_path = self.which_agent()
        app_exists = Path("/Applications/Cursor.app").exists()
        return {
            "cursor_cli": cursor_path,
            "agent_cli": agent_path,
            "cursor_app": app_exists,
            "ok": bool(cursor_path or app_exists) and bool(agent_path),
        }

    def check_authentication(self) -> dict[str, Any]:
        agent = self.which_agent()
        if not agent:
            return {"authenticated": False, "error": "Cursor Agent CLI není nainstalovaný (`agent`)"}
        try:
            result = subprocess.run(
                [agent, "status"],
                capture_output=True,
                text=True,
                timeout=30,
                env=self._env(),
                check=False,
            )
        except subprocess.TimeoutExpired:
            return {
                "authenticated": False,
                "error": "agent status timeout — spusť `agent login` v terminálu",
            }
        text = (result.stdout or "") + "\n" + (result.stderr or "")
        lower = text.lower()
        authenticated = result.returncode == 0 and "not authenticated" not in lower and "log in" not in lower
        # Some builds print account info on success.
        if "logged in" in lower or "email" in lower or "authenticated" in lower:
            authenticated = True
        if result.returncode != 0 and ("login" in lower or "auth" in lower):
            authenticated = False
        return {
            "authenticated": authenticated,
            "returncode": result.returncode,
            "output": text.strip()[:2000],
            "hint": None if authenticated else "Spusť v terminálu: agent login",
        }

    def open_project(self, path: str) -> dict[str, Any]:
        resolved = str(Path(path).expanduser().resolve())
        if not Path(resolved).is_dir():
            raise FileNotFoundError(f"Projekt neexistuje: {resolved}")
        cursor = self.which_cursor()
        if cursor:
            subprocess.Popen([cursor, resolved], env=self._env())
        else:
            subprocess.Popen(["open", "-a", "Cursor", resolved])
        return {"opened": resolved, "via": cursor or "Cursor.app"}

    def start_coding_task(
        self,
        workspace: str,
        prompt: str,
        on_output: Callable[[str], None] | None = None,
        timeout: float | None = None,
    ) -> AgentRun:
        auth = self.check_authentication()
        if not auth.get("authenticated"):
            raise RuntimeError(auth.get("hint") or auth.get("error") or "Cursor Agent není přihlášený")
        agent = self.which_agent()
        if not agent:
            raise RuntimeError("agent CLI nenalezen")
        workspace = str(Path(workspace).expanduser().resolve())
        run_id = str(uuid.uuid4())
        cmd = [
            agent,
            "-p",
            prompt,
            "--workspace",
            workspace,
            "--output-format",
            self.output_format,
        ]
        if self.force:
            cmd.append("--force")
        if self.trust:
            cmd.append("--trust")

        run = AgentRun(id=run_id, workspace=workspace, prompt=prompt, status="running", started_at=time.time())
        with self._lock:
            self._runs[run_id] = run

        def worker() -> None:
            try:
                proc = subprocess.Popen(
                    cmd,
                    cwd=workspace,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    env=self._env(),
                    start_new_session=True,
                )
                run.pid = proc.pid
                run.process = proc
                assert proc.stdout is not None
                chunks: list[str] = []
                deadline = time.time() + (timeout or self.default_timeout)
                while True:
                    if time.time() > deadline:
                        self.cancel(run_id)
                        run.status = "failed"
                        run.error = "Timeout Cursor Agent úkolu"
                        break
                    if run.status == "cancelled":
                        break
                    line = proc.stdout.readline()
                    if not line and proc.poll() is not None:
                        break
                    if line:
                        chunks.append(line)
                        if on_output:
                            on_output(line)
                code = proc.wait(timeout=5) if proc.poll() is None else proc.returncode
                run.output = "".join(chunks)
                run.finished_at = time.time()
                if run.status == "cancelled":
                    return
                if code == 0:
                    run.status = "ok"
                else:
                    run.status = "failed"
                    run.error = f"agent exit code {code}"
            except Exception as exc:  # noqa: BLE001
                run.status = "failed"
                run.error = str(exc)
                run.finished_at = time.time()
                logger.exception("Cursor agent run failed")

        threading.Thread(target=worker, name=f"cursor-agent-{run_id[:8]}", daemon=True).start()
        return run

    def wait(self, run_id: str, poll: float = 0.5) -> AgentRun:
        while True:
            run = self.get(run_id)
            if run.status in {"ok", "failed", "cancelled"}:
                return run
            time.sleep(poll)

    def get(self, run_id: str) -> AgentRun:
        with self._lock:
            if run_id not in self._runs:
                raise KeyError(run_id)
            return self._runs[run_id]

    def cancel(self, run_id: str) -> dict[str, Any]:
        with self._lock:
            run = self._runs.get(run_id)
        if not run:
            return {"cancelled": False, "error": "Úkol nenalezen"}
        run.status = "cancelled"
        if run.pid:
            try:
                os.killpg(run.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            except Exception:  # noqa: BLE001
                try:
                    if run.process:
                        run.process.terminate()
                except Exception:  # noqa: BLE001
                    pass
        run.finished_at = time.time()
        return {"cancelled": True, "run_id": run_id}

    def inspect_git_changes(self, workspace: str) -> dict[str, Any]:
        workspace = str(Path(workspace).expanduser().resolve())

        def git(*args: str) -> str:
            result = subprocess.run(
                ["git", *args],
                cwd=workspace,
                capture_output=True,
                text=True,
                check=False,
            )
            return (result.stdout or result.stderr or "").strip()

        if not (Path(workspace) / ".git").exists():
            return {"is_git": False, "status": "", "diff_stat": ""}
        return {
            "is_git": True,
            "status": git("status", "--short"),
            "diff_stat": git("diff", "--stat"),
            "diff_stat_cached": git("diff", "--cached", "--stat"),
        }

    def summarize_stream_json(self, output: str) -> str:
        texts: list[str] = []
        for line in output.splitlines():
            line = line.strip()
            if not line.startswith("{"):
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            if obj.get("type") in {"assistant", "message"}:
                msg = obj.get("message") or obj
                content = msg.get("content")
                if isinstance(content, str):
                    texts.append(content)
                elif isinstance(content, list):
                    for block in content:
                        if isinstance(block, dict) and block.get("type") == "text":
                            texts.append(str(block.get("text", "")))
            if "result" in obj and isinstance(obj["result"], str):
                texts.append(obj["result"])
        joined = "\n".join(t for t in texts if t).strip()
        return joined[:4000] if joined else output[-2000:]
