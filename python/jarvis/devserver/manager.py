"""Development server detection, launch, readiness, and lifecycle."""

from __future__ import annotations

import json
import logging
import os
import re
import signal
import subprocess
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.request import urlopen

logger = logging.getLogger(__name__)

URL_RE = re.compile(r"https?://(?:localhost|127\.0\.0\.1|0\.0\.0\.0)(?::(\d+))?[^\s]*", re.I)
PORT_RE = re.compile(r"(?:port|localhost|127\.0\.0\.1|Local:|ready on)[^\d]{0,20}(\d{2,5})", re.I)


@dataclass
class DetectedServer:
    command: str
    cwd: str
    framework: str
    suggested_url: str | None = None
    suggested_port: int | None = None
    source: str = "package.json"


@dataclass
class RunningServer:
    id: str
    project_alias: str
    command: str
    cwd: str
    pid: int | None = None
    url: str | None = None
    port: int | None = None
    status: str = "starting"
    output: str = ""
    process: subprocess.Popen[str] | None = field(default=None, repr=False)
    db_id: int | None = None


class DevelopmentServerManager:
    def __init__(self, health_timeout: float = 90.0, poll_interval: float = 1.0) -> None:
        self.health_timeout = health_timeout
        self.poll_interval = poll_interval
        self._servers: dict[str, RunningServer] = {}
        self._lock = threading.Lock()

    def detect(self, project_path: str) -> list[DetectedServer]:
        root = Path(project_path).expanduser().resolve()
        found: list[DetectedServer] = []
        pkg = root / "package.json"
        if pkg.exists():
            data = json.loads(pkg.read_text(encoding="utf-8"))
            scripts = data.get("scripts") or {}
            deps = {**(data.get("dependencies") or {}), **(data.get("devDependencies") or {})}
            framework = "node"
            default_port = 3000
            if "vite" in deps or (root / "vite.config.js").exists() or (root / "vite.config.ts").exists():
                framework = "vite"
                default_port = 5173
            elif "next" in deps or (root / "next.config.js").exists() or (root / "next.config.mjs").exists():
                framework = "next"
                default_port = 3000
            elif "react-scripts" in deps:
                framework = "cra"
                default_port = 3000
            for key in ("dev", "start", "serve"):
                if key in scripts:
                    cmd = f"npm run {key}"
                    found.append(
                        DetectedServer(
                            command=cmd,
                            cwd=str(root),
                            framework=framework,
                            suggested_port=default_port,
                            suggested_url=f"http://127.0.0.1:{default_port}",
                            source=f"package.json#scripts.{key}",
                        )
                    )
                    break
        if (root / "manage.py").exists():
            found.append(
                DetectedServer(
                    command="python manage.py runserver",
                    cwd=str(root),
                    framework="django",
                    suggested_port=8000,
                    suggested_url="http://127.0.0.1:8000",
                    source="manage.py",
                )
            )
        if (root / "pyproject.toml").exists() and not found:
            text = (root / "pyproject.toml").read_text(encoding="utf-8", errors="ignore")
            if "uvicorn" in text or "fastapi" in text:
                found.append(
                    DetectedServer(
                        command="uvicorn main:app --reload",
                        cwd=str(root),
                        framework="fastapi",
                        suggested_port=8000,
                        suggested_url="http://127.0.0.1:8000",
                        source="pyproject.toml",
                    )
                )
        return found

    def find_active(self, project_alias: str) -> RunningServer | None:
        with self._lock:
            for server in self._servers.values():
                if server.project_alias.lower() == project_alias.lower() and server.status in {
                    "starting",
                    "running",
                }:
                    return server
        return None

    def start(
        self,
        project_alias: str,
        command: str,
        cwd: str,
        suggested_port: int | None = None,
        suggested_url: str | None = None,
    ) -> RunningServer:
        existing = self.find_active(project_alias)
        if existing and existing.url:
            # Reuse if still reachable.
            if self.http_ready(existing.url, timeout=2):
                return existing

        server_id = f"{project_alias}-{int(time.time())}"
        server = RunningServer(
            id=server_id,
            project_alias=project_alias,
            command=command,
            cwd=cwd,
            port=suggested_port,
            url=suggested_url,
            status="starting",
        )
        with self._lock:
            self._servers[server_id] = server

        def worker() -> None:
            try:
                proc = subprocess.Popen(
                    command,
                    cwd=cwd,
                    shell=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    env=os.environ.copy(),
                    start_new_session=True,
                )
                server.pid = proc.pid
                server.process = proc
                chunks: list[str] = []
                deadline = time.time() + self.health_timeout
                assert proc.stdout is not None
                while time.time() < deadline and server.status == "starting":
                    line = proc.stdout.readline()
                    if line:
                        chunks.append(line)
                        server.output = "".join(chunks)[-20000:]
                        parsed = self.parse_url_port(server.output)
                        if parsed["url"]:
                            server.url = parsed["url"]
                        if parsed["port"]:
                            server.port = parsed["port"]
                        if server.url and self.http_ready(server.url, timeout=1.5):
                            server.status = "running"
                            return
                    if proc.poll() is not None:
                        server.status = "failed"
                        server.output = "".join(chunks)[-20000:]
                        return
                    if not line:
                        time.sleep(self.poll_interval)
                        # Try suggested URL even without log parse.
                        if server.url and self.http_ready(server.url, timeout=1.0):
                            server.status = "running"
                            return
                if server.status == "starting":
                    if server.url and self.http_ready(server.url, timeout=2):
                        server.status = "running"
                    else:
                        server.status = "failed"
            except Exception as exc:  # noqa: BLE001
                server.status = "failed"
                server.output = str(exc)
                logger.exception("Dev server failed")

        threading.Thread(target=worker, name=f"devserver-{server_id}", daemon=True).start()
        return server

    def wait_until_ready(self, server_id: str, timeout: float | None = None) -> RunningServer:
        deadline = time.time() + (timeout or self.health_timeout)
        while time.time() < deadline:
            server = self.get(server_id)
            if server.status in {"running", "failed", "stopped"}:
                return server
            time.sleep(self.poll_interval)
        server = self.get(server_id)
        if server.status == "starting":
            server.status = "failed"
        return server

    def get(self, server_id: str) -> RunningServer:
        with self._lock:
            if server_id not in self._servers:
                raise KeyError(server_id)
            return self._servers[server_id]

    def stop(self, server_id: str) -> dict[str, Any]:
        server = self.get(server_id)
        if server.pid:
            try:
                os.killpg(server.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            except Exception:  # noqa: BLE001
                if server.process:
                    server.process.terminate()
        server.status = "stopped"
        return {"stopped": True, "server_id": server_id}

    def stop_project(self, project_alias: str) -> dict[str, Any]:
        server = self.find_active(project_alias)
        if not server:
            return {"stopped": False, "error": "Žádný běžící server"}
        return self.stop(server.id)

    @staticmethod
    def parse_url_port(text: str) -> dict[str, Any]:
        url = None
        port = None
        match = URL_RE.search(text)
        if match:
            url = match.group(0).rstrip(".,)")
            # Normalize 0.0.0.0 → 127.0.0.1 for browser.
            url = url.replace("0.0.0.0", "127.0.0.1")
            if match.group(1):
                port = int(match.group(1))
        if port is None:
            pm = PORT_RE.search(text)
            if pm:
                port = int(pm.group(1))
        if url is None and port is not None:
            url = f"http://127.0.0.1:{port}"
        return {"url": url, "port": port}

    @staticmethod
    def http_ready(url: str, timeout: float = 2.0) -> bool:
        try:
            with urlopen(url, timeout=timeout) as resp:  # noqa: S310 — local health check only
                return 200 <= getattr(resp, "status", 200) < 500
        except URLError:
            return False
        except Exception:  # noqa: BLE001
            return False
