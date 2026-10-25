# J.A.R.V.I.S. — Instalace a spuštění (macOS Apple Silicon)

## Požadavky

- macOS na Apple Silicon
- Python 3.12+
- Xcode Command Line Tools / Xcode (pro menu-bar UI)
- [LM Studio](https://lmstudio.ai/) s načteným chat modelem (výchozí: `google/gemma-4-e4b`) a Local Server (výchozí: `http://192.168.0.192:1234`)
- Cursor + Cursor Agent CLI
- Mikrofon; Accessibility (a podle potřeby Automation / Screen Recording)

## 1. Setup + appka (nejjednodušší)

```bash
cd /cesta/k/Jarvis-Extension-for-CursorAI
chmod +x scripts/*.sh
./scripts/setup.sh          # jednou: Python závislosti
./scripts/install-app.sh    # sestaví JARVIS.app → ~/Applications a spustí
```

Pak stačí otevírat **JARVIS** z `~/Applications` (nebo Spotlight).  
Backend se spouští sám s appkou; ikona je v menu baru.

Jen znovu sestavit bez instalace:

```bash
./scripts/build-app.sh
open dist/JARVIS.app
```

## 2. Cursor Agent (bez API klíče)

```bash
# pokud chybí:
curl https://cursor.com/install -fsS | bash
export PATH="$HOME/.local/bin:$PATH"

agent login
agent status
```

## 3. LM Studio

1. Spusť LM Studio na PC (nebo Macu), kde běží model.
2. Načti chat model — aktuálně: **`google/gemma-4-e4b`**.
3. Zapni Local Server na portu **1234**.
4. Pokud JARVIS běží na jiném zařízení, v LM Studio povol poslech na síti (Server Settings → bind `0.0.0.0`, ne jen `127.0.0.1`) a případně povol firewall port 1234.
5. Ověření z Macu s JARVISem:

```bash
curl http://192.168.0.192:1234/v1/models
```

Konfigurace je v `config/default.toml` a v `~/Library/Application Support/JARVIS/config.toml`:

```toml
[llm]
base_url = "http://192.168.0.192:1234/v1"
model = "google/gemma-4-e4b"
```

## 4. Registrace projektu

```bash
./scripts/register-project.sh XXWorkplace "/absolutní/cesta/k/XXWorkplace"
```

Alias se ukládá do SQLite (`~/Library/Application Support/JARVIS/jarvis.db`). Cesta se **nevymýšlí**.

## 5. Spuštění

**Doporučeno:** `./scripts/install-app.sh` nebo otevři `~/Applications/JARVIS.app`.

Vývojářské alternativy:

```bash
./scripts/start-backend.sh          # jen Python
./scripts/start.sh                  # backend + swift run
source .venv/bin/activate
python -m jarvis.main --no-wake --text "Jarvisi, co teď děláš?"
```

## 6. Oprávnění macOS

Při prvním použití povol:

| Oprávnění | Proč |
|-----------|------|
| Mikrofon | **Push-to-talk** (nahrává Swift v JARVIS.app — musí být povolený pro JARVIS) |
| Accessibility | Okna, AX strom, klikání |
| Automation | AppleScript / System Events |
| Screen Recording | Jen fallback screenshot |

Diagnostika je v menu-bar Settings / tool `permission_diagnostics`.

## 7. Hlasové ovládání

Wake fráze:

- „Hej Jarvisi…“
- „Hej Jarve…“
- „Jarvisi…“
- „Jarve…“

Záloha: **Push-to-talk** v menu baru.

Příklad acceptance flow:

1. „Jarvisi, otevři Cursor na projektu XXWorkplace, uprav dashboard, spusť aplikaci a otevři localhost.“
2. JARVIS shrne plán a zeptá se „Mám začít?“
3. „Jo.“
4. Proběhne workflow: Cursor → Agent → verify → dev server → health → browser → český report.

## 8. Testy

```bash
source .venv/bin/activate
pytest -q
```

## Ověřené / Neověřené

Viz [README.md](../README.md) sekce Výsledky.
