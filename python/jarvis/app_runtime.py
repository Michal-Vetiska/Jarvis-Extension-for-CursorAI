"""Core JARVIS runtime wiring services together."""

from __future__ import annotations

import json
import logging
import re
import threading
import uuid
from pathlib import Path
from typing import Any

from jarvis.config import AppConfig, load_config
from jarvis.cursor_adapter import CursorAgentAdapter
from jarvis.db import Database
from jarvis.devserver import DevelopmentServerManager
from jarvis.ipc import IpcServer
from jarvis.llm import LLMClient
from jarvis.macos import apps as macos_apps
from jarvis.orchestrator import Step, WorkflowContext, WorkflowEngine
from jarvis.paths import socket_path
from jarvis.tools import build_registry
from jarvis.tools.registry_factory import run_shell_approved
from jarvis.voice import MacSayTTS, SpeechToText, VoiceSession, WakeWordListener

logger = logging.getLogger(__name__)

CONFIRM_YES = re.compile(r"^\s*(ano|jo|jasně|jasne|ok|okay|pokračuj|pokracuj|souhlasím|souhlasim|yes)\b", re.I)
CONFIRM_NO = re.compile(r"^\s*(ne|stop|zruš|zrus|cancel|nikdy)\b", re.I)
# Chat bez tools = rychlá odpověď (Gemma + velký tool list je brutálně pomalý)
CHAT_ONLY_RE = re.compile(
    r"^\s*(ahoj|čau|cau|nazdar|dobrý den|dobry den|děkuju|dekuju|díky|diky|"
    r"jak se máš|jak se mas|kdo jsi|co umíš|co umis|dobrou noc|bye|hi|hello)\b",
    re.I,
)
# Tools jen když to vypadá na akci
ACTION_RE = re.compile(
    r"\b(otevři|otevri|spusť|spust|zavři|zavri|cursor|projekt|localhost|server|"
    r"uprav|napiš|napis|commit|git|finder|okno|aplikac|workflow|dashboard|"
    r"zaregistruj|alias|browser|prohlížeč|prohlizec)\b",
    re.I,
)


class JarvisRuntime:
    def __init__(self, config: AppConfig | None = None) -> None:
        self.config = config or load_config()
        self.db = Database(self.config.data_directory / "jarvis.db")
        cursor_cfg = self.config.cursor
        self.cursor = CursorAgentAdapter(
            agent_bin=str(cursor_cfg.get("agent_bin", "agent")),
            cursor_bin=str(cursor_cfg.get("cursor_bin", "cursor")),
            path_hint=str(cursor_cfg.get("agent_path_hint", "~/.local/bin")),
            force=bool(cursor_cfg.get("force", True)),
            trust=bool(cursor_cfg.get("trust", True)),
            output_format=str(cursor_cfg.get("output_format", "stream-json")),
            default_timeout=float(cursor_cfg.get("default_timeout_seconds", 900)),
        )
        ds = self.config.devserver
        self.devservers = DevelopmentServerManager(
            health_timeout=float(ds.get("health_timeout_seconds", 90)),
            poll_interval=float(ds.get("health_poll_interval_seconds", 1.0)),
        )
        llm = self.config.llm
        self.llm = LLMClient(
            base_url=str(llm.get("base_url", "http://127.0.0.1:1234/v1")),
            api_key=str(llm.get("api_key", "lm-studio")),
            model=str(llm.get("model", "local-model")),
            temperature=float(llm.get("temperature", 0.3)),
            timeout=float(llm.get("timeout_seconds", 45)),
        )
        voice = self.config.voice
        self.tts = MacSayTTS(
            voice=str(voice.get("tts_voice", "Zuzana")),
            fallback_voice=str(voice.get("tts_fallback_voice", "Samantha")),
        )
        self.stt = SpeechToText(
            backend=str(voice.get("stt_backend", "mlx_whisper")),
            model=str(voice.get("stt_model", "mlx-community/whisper-small-mlx")),
            language=str(voice.get("stt_language", "cs")),
        )
        self.wake = WakeWordListener(
            threshold=float(voice.get("wake_threshold", 0.55)),
            sample_rate=int(voice.get("sample_rate", 16000)),
            phrases=list(voice.get("wake_phrases", [])),
        )
        self.voice = VoiceSession(
            stt=self.stt,
            tts=self.tts,
            wake=self.wake,
            sample_rate=int(voice.get("sample_rate", 16000)),
            on_utterance=self.handle_user_text,
            on_state=self._on_voice_state,
        )
        self.tools = build_registry(self)
        self.workflow = WorkflowEngine(on_update=self._on_workflow_update)
        self.ipc: IpcServer | None = None
        self._messages: list[dict[str, Any]] = []
        self._pending_confirmation: dict[str, Any] | None = None
        self._state_lock = threading.Lock()
        self._ui_state: dict[str, Any] = {
            "voice_state": "idle",
            "listening": False,
            "task": None,
            "active_project": None,
            "server": None,
            "cursor": None,
            "transcript": [],
        }
        self._agent_run_id: str | None = None

    # --- lifecycle ---

    def start(self) -> None:
        sock = socket_path(self.config.data_directory, self.config.ipc_socket_name)
        self.ipc = IpcServer(sock, self._ipc_handlers())
        self.ipc.start()
        if self.config.voice.get("wake_enabled", True):
            self.voice.start()
        self._broadcast_state()
        logger.info("JARVIS runtime started")

    def stop(self) -> None:
        self.voice.stop()
        if self.ipc:
            self.ipc.stop()

    def _ipc_handlers(self) -> dict[str, Any]:
        return {
            "ping": lambda _: {"pong": True, "version": "0.1.0"},
            "get_state": lambda _: self.snapshot(),
            "push_to_talk": lambda _: self._ptt(),
            "stop_speaking": lambda _: self.tts.stop() or {"stopped": True},
            "cancel_task": lambda p: self.cancel_task(p.get("task_id")),
            "stop_server": lambda p: self.stop_dev_server(p.get("alias") or ""),
            "open_localhost": lambda p: self._open_localhost(p.get("alias")),
            "list_tools": lambda _: {"tools": self.tools.list_tools()},
            "execute_tool": lambda p: self._execute_tool_ipc(p),
            "register_project": lambda p: self.register_project(p["alias"], p["path"]),
            "submit_text": lambda p: self._submit_text_ipc(p.get("text", "")),
            "submit_audio": lambda p: self._submit_audio_ipc(p),
            "permission_diagnostics": lambda _: macos_apps.permission_diagnostics(),
            "llm_health": lambda _: self.llm.health(),
            "cursor_status": lambda _: self.cursor_status(),
            "list_tts_voices": lambda _: {"voices": self.tts.available_voices()},
            "set_voice_settings": lambda p: self._set_voice_settings(p),
            "set_llm_settings": lambda p: self._set_llm_settings(p),
            "get_llm_settings": lambda _: {
                "base_url": self.config.llm.get("base_url"),
                "model": self.config.llm.get("model"),
                "health": self.llm.health(),
            },
        }

    def _ptt(self) -> dict[str, Any]:
        # Preferuj Swift nahrávání (submit_audio). Python PTT jen jako fallback.
        self.voice.push_to_talk_start()
        return {"started": True, "note": "prefer_submit_audio"}

    def _submit_text_ipc(self, text: str) -> dict[str, Any]:
        threading.Thread(target=self.handle_user_text, args=(text,), daemon=True).start()
        return {"accepted": True}

    def _set_voice_settings(self, params: dict[str, Any]) -> dict[str, Any]:
        voice = params.get("tts_voice")
        # `say -a` typicky chce jméno zařízení; UID často nefunguje
        output_name = (params.get("output_name") or "").strip()
        output_uid = params.get("output_uid") or ""
        device = output_name or None
        if output_uid in {"", "__system_default__", "default"}:
            device = None
        result = self.tts.set_settings(voice=voice, audio_device=device)
        self.db.set_setting("tts_voice", result.get("tts_voice") or "")
        self.db.set_setting("tts_audio_device", result.get("audio_device") or "")
        return {"ok": True, **result}

    def _set_llm_settings(self, params: dict[str, Any]) -> dict[str, Any]:
        base_url = (params.get("base_url") or "").strip().rstrip("/")
        model = (params.get("model") or "").strip()
        if base_url and not base_url.endswith("/v1"):
            base_url = base_url + "/v1"
        raw = dict(self.config.raw)
        llm = dict(raw.get("llm") or {})
        if base_url:
            llm["base_url"] = base_url
        if model:
            llm["model"] = model
        raw["llm"] = llm
        self.config.raw = raw
        # Přepni klienta za běhu
        self.llm = LLMClient(
            base_url=str(llm.get("base_url", "http://127.0.0.1:1234/v1")),
            api_key=str(llm.get("api_key", "lm-studio")),
            model=str(llm.get("model", "local-model")),
            temperature=float(llm.get("temperature", 0.3)),
            timeout=float(llm.get("timeout_seconds", 45)),
        )
        # Persist do user config
        user_cfg = self.config.data_directory / "config.toml"
        try:
            import tomllib

            existing: dict[str, Any] = {}
            if user_cfg.exists():
                with user_cfg.open("rb") as fh:
                    existing = tomllib.load(fh)
            existing.setdefault("llm", {})
            existing["llm"]["base_url"] = llm.get("base_url")
            existing["llm"]["model"] = llm.get("model")
            # jednoduchý TOML dump jen pro llm klíče — zachovej zbytek souboru přes rewrite sekce
            self._write_user_llm_config(user_cfg, existing)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Nepodařilo se uložit LLM config: %s", exc)
        health = self.llm.health()
        return {"ok": True, "base_url": llm.get("base_url"), "model": llm.get("model"), "health": health}

    def _write_user_llm_config(self, path: Path, existing: dict[str, Any]) -> None:
        """Aktualizuje [llm] base_url/model v user config.toml (best-effort)."""
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            default = Path(__file__).resolve().parents[2] / "config" / "default.toml"
            if default.exists():
                path.write_text(default.read_text(encoding="utf-8"), encoding="utf-8")
        text = path.read_text(encoding="utf-8") if path.exists() else ""
        base = existing.get("llm", {}).get("base_url", "http://127.0.0.1:1234/v1")
        model = existing.get("llm", {}).get("model", "local-model")
        lines = text.splitlines()
        out: list[str] = []
        in_llm = False
        seen_base = seen_model = False
        for line in lines:
            stripped = line.strip()
            if stripped.startswith("[") and stripped.endswith("]"):
                if in_llm:
                    if not seen_base:
                        out.append(f'base_url = "{base}"')
                    if not seen_model:
                        out.append(f'model = "{model}"')
                in_llm = stripped == "[llm]"
                out.append(line)
                continue
            if in_llm and stripped.startswith("base_url"):
                out.append(f'base_url = "{base}"')
                seen_base = True
                continue
            if in_llm and stripped.startswith("model"):
                out.append(f'model = "{model}"')
                seen_model = True
                continue
            out.append(line)
        if in_llm:
            if not seen_base:
                out.append(f'base_url = "{base}"')
            if not seen_model:
                out.append(f'model = "{model}"')
        if "[llm]" not in text:
            out.extend(["", "[llm]", f'base_url = "{base}"', f'model = "{model}"'])
        path.write_text("\n".join(out) + "\n", encoding="utf-8")

    def _submit_audio_ipc(self, params: dict[str, Any]) -> dict[str, Any]:
        """Audio nahrané ve Swiftu (má TCC mikrofon) → STT → planner."""
        path = params.get("path")
        if not path or not Path(path).is_file():
            return {"ok": False, "text": "", "error": "Audio soubor neexistuje"}
        self._on_voice_state("transcribing")
        try:
            text = self.stt.transcribe_wav_file(str(path))
            text = (text or "").strip()
            lowered = text.lower()
            for phrase in (
                "hej adame",
                "ahoj adame",
                "hej adam",
                "ahoj adam",
                "hey adam",
                "adame",
                "adam",
            ):
                if lowered.startswith(phrase):
                    text = text[len(phrase) :].lstrip(" ,.")
                    break
            if not text:
                self._on_voice_state("idle")
                return {"ok": False, "text": "", "error": "Prázdný přepis — zkus mluvit hlasitěji"}
            # Text vrať hned; planner běží na pozadí (LLM může trvat)
            threading.Thread(target=self.handle_user_text, args=(text,), daemon=True).start()
            self._on_voice_state("idle")
            return {"ok": True, "text": text}
        except Exception as exc:  # noqa: BLE001
            logger.exception("submit_audio failed")
            self._on_voice_state("error")
            return {"ok": False, "text": "", "error": str(exc)}

    def _execute_tool_ipc(self, params: dict[str, Any]) -> dict[str, Any]:
        name = params.get("name")
        args = params.get("arguments") or {}
        confirmed = bool(params.get("confirmed", False))
        result = self.tools.execute(name, args, confirmed=confirmed)
        return {
            "ok": result.ok,
            "data": result.data,
            "error": result.error,
            "needs_confirmation": result.needs_confirmation,
            "permission": result.permission,
        }

    def _open_localhost(self, alias: str | None) -> dict[str, Any]:
        if not alias:
            servers = self.db.active_servers()
            if not servers:
                return {"ok": False, "error": "Žádný aktivní server"}
            url = servers[0].get("url")
        else:
            server = self.db.get_server_for_project(alias) or (
                self.devservers.find_active(alias).__dict__
                if self.devservers.find_active(alias)
                else None
            )
            url = server.get("url") if server else None
        if not url:
            return {"ok": False, "error": "URL není známá"}
        return macos_apps.open_url(url)

    # --- UI state ---

    def snapshot(self) -> dict[str, Any]:
        with self._state_lock:
            state = dict(self._ui_state)
            state["transcript"] = list(state.get("transcript") or [])
            state["task"] = self.workflow.current
            state["projects"] = [p.__dict__ for p in self.db.list_projects()]
            state["pending_confirmation"] = self._pending_confirmation
            state["llm"] = state.get("llm") or {
                "base_url": self.config.llm.get("base_url"),
                "model": self.config.llm.get("model"),
            }
            return state

    def _broadcast_state(self) -> None:
        if self.ipc:
            self.ipc.broadcast("state", self.snapshot())

    def _on_voice_state(self, state: str) -> None:
        with self._state_lock:
            self._ui_state["voice_state"] = state
            self._ui_state["listening"] = state == "listening"
        self._broadcast_state()

    def _on_workflow_update(self, state: dict[str, Any]) -> None:
        self.db.upsert_task(
            task_id=state["task_id"],
            title=state.get("title") or "Úkol",
            status=state.get("status") or "running",
            project_alias=state.get("alias"),
            current_step=state.get("current_step"),
            payload={"instruction": state.get("instruction")},
            result=state.get("result"),
            error=state.get("error"),
        )
        with self._state_lock:
            self._ui_state["task"] = state
            self._ui_state["active_project"] = state.get("alias")
        self._broadcast_state()

    def _append_transcript(self, role: str, content: str) -> None:
        self.db.add_message(role, content)
        with self._state_lock:
            self._ui_state.setdefault("transcript", []).append({"role": role, "content": content})
            self._ui_state["transcript"] = self._ui_state["transcript"][-100:]
        self._broadcast_state()

    # --- conversation ---

    def speak(self, text: str, wait: bool = False) -> dict[str, Any]:
        """Text do UI hned; TTS defaultně neblokuje (rychlejší pocit odpovědi)."""
        self._append_transcript("assistant", text)
        with self._state_lock:
            self._ui_state["voice_state"] = "speaking"
            self._ui_state["llm"] = {**(self._ui_state.get("llm") or {}), "status": "ok"}
        self._broadcast_state()
        self.voice.speak(text, wait=wait)
        with self._state_lock:
            self._ui_state["voice_state"] = "idle"
        self._broadcast_state()
        return {"spoken": True, "text": text}

    def handle_user_text(self, text: str) -> None:
        text = (text or "").strip()
        if not text:
            return
        # Swift UI už často zobrazí user řádek — do DB/UI zapisuj jen když ještě není poslední stejný
        with self._state_lock:
            recent = self._ui_state.get("transcript") or []
            already = bool(recent) and recent[-1].get("role") == "user" and recent[-1].get("content") == text
        if not already:
            self._append_transcript("user", text)
        else:
            self.db.add_message("user", text)

        # Confirmation gate
        if self._pending_confirmation:
            if CONFIRM_YES.search(text):
                pending = self._pending_confirmation
                self._pending_confirmation = None
                self._run_confirmed(pending)
                return
            if CONFIRM_NO.search(text):
                self._pending_confirmation = None
                self.speak("Dobře, ruším to.")
                return
            self.speak("Prosím potvrď ano, nebo řekni ne.")
            return

        # Fast path: status question
        if re.search(r"co (teď|ted) děláš|co deláš|stav úkolu|stav ukolu", text, re.I):
            status = self.get_task_status(None)
            msg = self._format_status_cs(status)
            self.speak(msg)
            return

        # Okamžité lokální odpovědi (bez LLM) — ahoj atd.
        local = self._local_quick_reply(text)
        if local:
            self.speak(local)
            return

        self._planner_turn(text)

    def _local_quick_reply(self, text: str) -> str | None:
        t = text.lower().strip()
        if re.match(r"^(ahoj|čau|cau|nazdar|hi|hello)([\s,.!]|$)", t):
            return "Ahoj! Jsem Adam. Řekni třeba: Hej Adame, otevři projekt."
        if re.match(r"^(děkuju|dekuju|díky|diky)([\s,.!]|$)", t):
            return "Není zač."
        if re.search(r"kdo jsi", t):
            return "Jsem Adam, tvůj hlasový asistent na Macu."
        return None

    def _planner_turn(self, text: str) -> None:
        self._messages.append({"role": "user", "content": text})
        # Krátká historie = rychlejší inference
        history = self._messages[-6:]
        # Tools jen když to vypadá na akci — jinak čistý chat (řádově rychlejší)
        use_tools = bool(ACTION_RE.search(text)) and not CHAT_ONLY_RE.search(text)
        tools = self.tools.openai_tools() if use_tools else None

        with self._state_lock:
            self._ui_state["voice_state"] = "thinking"
            self._ui_state["llm"] = {
                "status": "calling",
                "base_url": self.config.llm.get("base_url"),
                "tools": use_tools,
            }
        self._broadcast_state()

        response = self.llm.chat(history, tools=tools, max_tokens=180 if not use_tools else 400)
        if not response.get("ok"):
            err = response.get("error") or "connection error"
            base = self.config.llm.get("base_url", "http://127.0.0.1:1234/v1")
            with self._state_lock:
                self._ui_state["llm"] = {"status": "offline", "error": err, "base_url": base}
                self._ui_state["voice_state"] = "error"
            self._broadcast_state()
            self.speak(
                "Nemůžu se spojit s LM Studio. Zapni Local Server a zkus to znovu."
            )
            logger.warning("LM Studio offline (%s): %s", base, err)
            return

        tool_calls = response.get("tool_calls") or []
        message = (response.get("message") or "").strip()

        if tool_calls:
            # If any tool needs confirmation, ask first (don't execute yet).
            for tc in tool_calls:
                preview = self.tools.execute(tc["name"], tc["arguments"], confirmed=False)
                if preview.needs_confirmation:
                    summary = message or self._summarize_plan(tool_calls)
                    self._pending_confirmation = {
                        "tool_calls": tool_calls,
                        "summary": summary,
                        "user_text": text,
                    }
                    ask = summary + (" Mám začít?" if not summary.endswith("?") else "")
                    self.speak(ask)
                    return
            # Execute tools that don't need confirmation
            self._execute_tool_calls(tool_calls, message)
            return

        if message:
            self.speak(message)
        else:
            self.speak("Nerozuměl jsem. Zkus to formulovat jinak.")

    def _summarize_plan(self, tool_calls: list[dict[str, Any]]) -> str:
        names = [tc["name"] for tc in tool_calls]
        if "run_autonomous_workflow" in names:
            args = next(tc["arguments"] for tc in tool_calls if tc["name"] == "run_autonomous_workflow")
            return (
                f"Rozumím. Otevřu projekt {args.get('alias')} v Cursoru, "
                f"provedu úpravy, spustím aplikaci a otevřu ji v prohlížeči."
            )
        return "Rozumím požadavku a potřebuji potvrzení před pokračováním."

    def _run_confirmed(self, pending: dict[str, Any]) -> None:
        self.speak("Rozumím, pouštím se do práce.")
        self._execute_tool_calls(pending["tool_calls"], pending.get("summary"))

    def _execute_tool_calls(self, tool_calls: list[dict[str, Any]], assistant_preamble: str | None) -> None:
        results = []
        for tc in tool_calls:
            result = self.tools.execute(tc["name"], tc["arguments"], confirmed=True)
            results.append({"name": tc["name"], "result": result.__dict__})
            self._messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tc.get("id") or tc["name"],
                    "content": json.dumps(result.__dict__, ensure_ascii=False)[:6000],
                }
            )

        # Lokální shrnutí nejdřív (bez druhého LLM round-tripu = výrazně rychlejší)
        failed = [r for r in results if not (r["result"] or {}).get("ok", True)]
        if failed:
            final = f"Úkol selhal: {failed[0]['result'].get('error')}"
        elif assistant_preamble:
            final = assistant_preamble
        else:
            names = ", ".join(r["name"] for r in results)
            final = f"Hotovo ({names})."
        self.speak(final)

    def _format_status_cs(self, status: dict[str, Any]) -> str:
        task = status.get("task")
        if not task:
            return "Teď nemám žádný běžící úkol."
        step = task.get("current_step") or "žádný"
        st = task.get("status")
        return f"Právě pracuji na úkolu ve stavu {st}, aktuální krok: {step}."

    # --- domain operations ---

    def register_project(self, alias: str, path: str) -> dict[str, Any]:
        project = self.db.register_project(alias, path)
        return {"alias": project.alias, "path": project.path, "id": project.id}

    def open_project_in_cursor(self, alias: str) -> dict[str, Any]:
        path = self.db.resolve_project_path(alias)
        result = self.cursor.open_project(path)
        with self._state_lock:
            self._ui_state["active_project"] = alias
        self._broadcast_state()
        return result

    def cursor_status(self) -> dict[str, Any]:
        info = {
            "installation": self.cursor.detect_installation(),
            "auth": self.cursor.check_authentication(),
        }
        with self._state_lock:
            self._ui_state["cursor"] = info
        return info

    def execute_coding_task(self, alias: str, instruction: str, timeout: float | None = None) -> dict[str, Any]:
        path = self.db.resolve_project_path(alias)
        self.cursor.open_project(path)
        run = self.cursor.start_coding_task(path, instruction, timeout=timeout)
        self._agent_run_id = run.id
        finished = self.cursor.wait(run.id)
        changes = self.cursor.inspect_git_changes(path)
        summary = self.cursor.summarize_stream_json(finished.output)
        ok = finished.status == "ok"
        return {
            "ok": ok,
            "run_id": finished.id,
            "status": finished.status,
            "error": finished.error,
            "summary": summary,
            "git": changes,
        }

    def inspect_git(self, alias: str) -> dict[str, Any]:
        path = self.db.resolve_project_path(alias)
        return self.cursor.inspect_git_changes(path)

    def run_validation(self, alias: str, command: str) -> dict[str, Any]:
        project = self.db.get_project(alias)
        if not project:
            raise KeyError(alias)
        if not self.db.is_command_approved(project.id, "validation", command):
            # Auto-approve common safe validators on explicit tool confirm path.
            self.db.approve_command(project.id, "validation", command, project.path)
        return run_shell_approved(command, project.path)

    def detect_dev_server(self, alias: str) -> dict[str, Any]:
        path = self.db.resolve_project_path(alias)
        detected = self.devservers.detect(path)
        return {
            "alias": alias,
            "path": path,
            "candidates": [d.__dict__ for d in detected],
        }

    def start_dev_server(self, alias: str, command: str | None = None, approve: bool = False) -> dict[str, Any]:
        project = self.db.get_project(alias)
        if not project:
            raise KeyError(alias)
        detected = self.devservers.detect(project.path)
        chosen = None
        if command:
            chosen_cmd = command
            port = None
            url = None
            for d in detected:
                if d.command == command:
                    port, url = d.suggested_port, d.suggested_url
                    break
        else:
            if not detected:
                return {"ok": False, "error": "Nenašel jsem vývojový příkaz"}
            chosen = detected[0]
            chosen_cmd = chosen.command
            port, url = chosen.suggested_port, chosen.suggested_url

        approved = self.db.is_command_approved(project.id, "devserver", chosen_cmd)
        if not approved:
            if not approve:
                return {
                    "ok": False,
                    "needs_approval": True,
                    "command": chosen_cmd,
                    "message": f"Nový příkaz vyžaduje schválení: {chosen_cmd}",
                }
            self.db.approve_command(project.id, "devserver", chosen_cmd, project.path)

        existing = self.devservers.find_active(alias)
        if existing and existing.status == "running" and existing.url:
            db_id = self.db.upsert_server(
                alias, existing.command, existing.cwd, "running", existing.pid, existing.url, existing.port
            )
            return {"ok": True, "reused": True, "url": existing.url, "port": existing.port, "server_id": existing.id, "db_id": db_id}

        server = self.devservers.start(alias, chosen_cmd, project.path, suggested_port=port, suggested_url=url)
        ready = self.devservers.wait_until_ready(server.id)
        status = "running" if ready.status == "running" else "failed"
        db_id = self.db.upsert_server(
            alias, ready.command, ready.cwd, status, ready.pid, ready.url, ready.port
        )
        with self._state_lock:
            self._ui_state["server"] = {
                "alias": alias,
                "url": ready.url,
                "port": ready.port,
                "status": ready.status,
            }
        self._broadcast_state()
        return {
            "ok": ready.status == "running",
            "server_id": ready.id,
            "url": ready.url,
            "port": ready.port,
            "status": ready.status,
            "output_tail": ready.output[-2000:],
            "db_id": db_id,
            "error": None if ready.status == "running" else "Server se nepodařilo nastartovat nebo není dostupný",
        }

    def stop_dev_server(self, alias: str) -> dict[str, Any]:
        if not alias:
            return {"ok": False, "error": "Chybí alias"}
        active = self.devservers.find_active(alias)
        result = self.devservers.stop_project(alias)
        if active:
            self.db.upsert_server(
                alias,
                active.command,
                active.cwd,
                "stopped",
                active.pid,
                active.url,
                active.port,
                server_id=active.db_id,
            )
        return result

    def dev_server_status(self) -> dict[str, Any]:
        return {"servers": self.db.active_servers()}

    def get_task_status(self, task_id: str | None = None) -> dict[str, Any]:
        current = self.workflow.current
        if task_id:
            row = self.db.get_task(task_id)
            return {"task": row, "live": current if current and current.get("task_id") == task_id else None}
        if current:
            return {"task": current}
        latest = self.db.latest_task()
        return {"task": latest}

    def cancel_task(self, task_id: str | None = None) -> dict[str, Any]:
        wf = self.workflow.cancel()
        if self._agent_run_id:
            self.cursor.cancel(self._agent_run_id)
        return {"workflow": wf, "task_id": task_id}

    def run_workflow(self, alias: str, instruction: str, timeout: float | None = None) -> dict[str, Any]:
        path = self.db.resolve_project_path(alias)

        def step_open(ctx: WorkflowContext) -> dict[str, Any]:
            return self.cursor.open_project(path)

        def step_code(ctx: WorkflowContext) -> dict[str, Any]:
            run = self.cursor.start_coding_task(path, instruction, timeout=timeout)
            self._agent_run_id = run.id
            finished = self.cursor.wait(run.id)
            if finished.status != "ok":
                raise RuntimeError(finished.error or "Cursor Agent selhal")
            return {
                "run_id": finished.id,
                "summary": self.cursor.summarize_stream_json(finished.output),
            }

        def step_verify(ctx: WorkflowContext) -> dict[str, Any]:
            return self.cursor.inspect_git_changes(path)

        def step_server(ctx: WorkflowContext) -> dict[str, Any]:
            result = self.start_dev_server(alias, approve=True)
            if not result.get("ok"):
                raise RuntimeError(result.get("error") or "Dev server selhal")
            ctx.data["url"] = result.get("url")
            ctx.data["port"] = result.get("port")
            return result

        def step_browser(ctx: WorkflowContext) -> dict[str, Any]:
            url = ctx.data.get("url")
            if not url:
                raise RuntimeError("Chybí URL serveru")
            return macos_apps.open_url(url)

        def step_report(ctx: WorkflowContext) -> dict[str, Any]:
            port = ctx.data.get("port")
            url = ctx.data.get("url")
            msg = (
                f"Úpravy jsou dokončené. Aplikace běží na localhostu"
                + (f" na portu {port}" if port else "")
                + " a otevřel jsem ji v prohlížeči. Můžeš ji zkontrolovat."
            )
            return {"message": msg, "url": url, "port": port}

        steps = [
            Step("OPEN_CURSOR", step_open, timeout=60),
            Step("EXECUTE_CODING_TASK", step_code, timeout=timeout or 900),
            Step("VERIFY_CHANGES", step_verify, timeout=60),
            Step("START_DEV_SERVER", step_server, timeout=120),
            Step("OPEN_BROWSER", step_browser, timeout=30),
            Step("REPORT_RESULT", step_report, timeout=10),
        ]
        result = self.workflow.run(
            title=f"Workflow {alias}",
            alias=alias,
            instruction=instruction,
            steps=steps,
        )
        # Truthful completion: only speak success via caller using result status.
        return result
