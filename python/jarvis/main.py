"""JARVIS backend entrypoint."""

from __future__ import annotations

import argparse
import logging
import signal
import sys
import time

from jarvis.app_runtime import JarvisRuntime
from jarvis.config import load_config
from jarvis.paths import log_dir


def setup_logging() -> None:
    log_dir().mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler(log_dir() / "jarvis.log", encoding="utf-8"),
        ],
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="JARVIS backend")
    parser.add_argument("--config", type=str, default=None)
    parser.add_argument("--no-wake", action="store_true")
    parser.add_argument("--register-project", nargs=2, metavar=("ALIAS", "PATH"))
    parser.add_argument("--text", type=str, help="Jednorázový textový příkaz (bez mikrofonu)")
    args = parser.parse_args(argv)

    setup_logging()
    overrides = {}
    if args.no_wake:
        overrides = {"voice": {"wake_enabled": False}}
    config = load_config(path=None if not args.config else __import__("pathlib").Path(args.config), overrides=overrides or None)
    runtime = JarvisRuntime(config)

    if args.register_project:
        alias, path = args.register_project
        result = runtime.register_project(alias, path)
        print(result)
        return 0

    runtime.start()

    def _shutdown(signum, frame):  # noqa: ANN001, ARG001
        logging.getLogger(__name__).info("Shutting down...")
        runtime.stop()
        sys.exit(0)

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    if args.text:
        runtime.handle_user_text(args.text)
        # Give async speech a moment.
        time.sleep(1)
        runtime.stop()
        return 0

    logging.getLogger(__name__).info("JARVIS běží. Wake word / IPC aktivní.")
    while True:
        time.sleep(1)


if __name__ == "__main__":
    raise SystemExit(main())
