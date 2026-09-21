"""Точка входа голосового ассистента "Соня"."""

import logging

import yaml
from dotenv import load_dotenv

from sona.orchestrator.main_loop import Orchestrator


def load_config(path: str = "config/config.yaml") -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def main() -> None:
    load_dotenv()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    config = load_config()
    orchestrator = Orchestrator(config)
    orchestrator.run_with_idle_watchdog()


if __name__ == "__main__":
    main()
