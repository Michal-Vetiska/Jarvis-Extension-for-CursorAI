# J.A.R.V.I.S. for macOS

Autonomní český hlasový asistent pro Apple Silicon: menu-bar UI (Swift), Python orchestrátor, LM Studio, lokální STT/TTS, Cursor Agent CLI, správa localhost vývojových serverů.

## Rychlý start (appka)

```bash
chmod +x scripts/*.sh
./scripts/setup.sh                              # jednou
./scripts/install-app.sh                        # → ~/Applications/JARVIS.app
./scripts/register-project.sh XXWorkplace "/cesta"
# LM Studio + agent login
```

Pak jen otevři **JARVIS** z Applications / Spotlight. Menu-bar ikona + backend startují spolu.

```bash
./scripts/build-app.sh    # jen sestavit do dist/JARVIS.app
```

Podrobnosti: [docs/INSTALACE.md](docs/INSTALACE.md)

## Architektura

- **Swift menu bar** ↔ Unix socket JSON-RPC ↔ **Python backend**
- Hlas: openWakeWord (`hey_jarvis`) + mlx-whisper (CS) + `say` (Zuzana)
- Plánování: LM Studio `/v1/chat/completions` + typed tools
- Coding: `cursor <path>` + `agent -p --force --trust --workspace …`
- DevServerManager: detekce frameworku, schválení příkazu, port parse, HTTP health, browser

## Bezpečnost

- Žádný neomezený shell z řeči
- Potvrzení před `PROJECT_MODIFICATION` / `PROCESS_EXECUTION` / `DESTRUCTIVE` / `EXTERNAL`
- Žádný silent git push / delete
- Klíče se nehardcodují (LM Studio local; Cursor přes `agent login`)

## Výsledky MVP

### Ověřené automatickými testy

Poslední běh: `pytest -q` → **14 passed**.

- Project registry (alias → cesta, odmítnutí neexistující cesty)
- Permission gates / confirmation
- Dev server URL/port parsing (Vite 5173, Next 3000)
- Workflow cancel
- IPC encode/decode + ping
- Wake phrase matching (Jarvisi / Jarve)
- Cursor adapter detect + stream-json summary
- Manuální smoke: IPC `ping` / `get_state`, registrace `DemoProject`, `swift build` OK

### Vyžaduje manuální E2E

- České STT přes mlx-whisper na reálném mikrofonu
- openWakeWord false-positive tuning
- Cursor Agent coding task po `agent login`
- LM Studio tool-calling kvalita závisí na modelu
- Accessibility / Automation dialogy na čistém Macu
- Celý acceptance scénář XXWorkplace → localhost

### Známá omezení

- LM Studio nemá Realtime/STT/TTS API — hlas je lokální kaskáda
- openWakeWord model je EN `hey_jarvis` (české „Jarvisi“ je přibližné)
- ScreenCaptureKit / Playwright nejsou v MVP (AX-first)
- Bez běžícího LM Studio a `agent login` není plný E2E

### Další priority

1. Doladění wake threshold + custom ONNX pro „Jarve“
2. Lepší stream progress ze `stream-json` do UI
3. Playwright verify vybraných UI assertů
4. Volitelný cloud LLM fallback
