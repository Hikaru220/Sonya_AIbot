"""Общий загрузчик config/app_aliases.yaml — используется и brain, и executor,
чтобы не парсить один и тот же файл дважды и не расходиться в обработке ошибок."""

import logging

import yaml

logger = logging.getLogger("sona.config.app_aliases")

DEFAULT_ALIASES_FILE = "config/app_aliases.yaml"


def load_app_aliases(aliases_file: str = DEFAULT_ALIASES_FILE) -> dict[str, dict]:
    """Возвращает {app_key: {"aliases": [...], "path": "..."}}.

    Битый/отсутствующий файл не роняет ассистента — просто возвращаем пустой словарь,
    залогировав ошибку; пользователь донастроит файл и перезапустит.
    """
    try:
        with open(aliases_file, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
    except Exception as exc:
        logger.error("Не удалось загрузить файл алиасов %s: %s", aliases_file, exc)
        return {}

    apps = {}
    for app_key, app_info in (data.get("apps") or {}).items():
        apps[app_key] = {
            "aliases": (app_info or {}).get("aliases", []),
            "path": (app_info or {}).get("path"),
        }
    return apps
