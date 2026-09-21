"""Доступ к файлам на диске: поиск, открытие, чтение вслух, создание.

Жёсткое правило безопасности: системные каталоги и папки с чувствительными данными
приложений (AppData, .git и т.п.) полностью исключены из поиска и недоступны для
операций — путь, попадающий под блок-лист, отклоняется на уровне кода, даже если
Gemini почему-то его предложит. Удаление/перемещение файлов сюда намеренно не входит.
Содержимое файлов наружу (в Gemini/поисковые API) никогда не передаётся — читается и
озвучивается полностью локально.
"""

import logging
import os
import string
import time
from pathlib import Path

logger = logging.getLogger("sona.files")

# Каталоги, которые никогда не сканируем и не трогаем ни при каких обстоятельствах.
_BLOCKED_DIR_NAMES = {
    "windows", "program files", "program files (x86)", "programdata",
    "$recycle.bin", "system volume information", "appdata",
    ".git", "node_modules", "__pycache__", "venv", ".venv",
}

# Где обычно лежат нужные пользователю файлы — проверяем в первую очередь. Без этого
# поиск по всей домашней папке может утонуть в посторонних деревьях (например, у
# разработчиков там нередко лежат SDK/кэши на десятки тысяч файлов) раньше, чем дойдёт
# до реального Рабочего стола или Документов.
_PRIORITY_DIR_NAMES = ("Desktop", "Рабочий стол", "Documents", "Downloads", "Pictures", "Videos", "Music")


class PathBlockedError(Exception):
    """Путь попадает под системный/чувствительный каталог — операция отклонена."""


def _is_blocked(path: Path) -> bool:
    return any(part.lower() in _BLOCKED_DIR_NAMES for part in path.parts)


def _assert_allowed(path: Path) -> None:
    if _is_blocked(path):
        logger.warning("Отклонён доступ к запрещённому пути: %s", path)
        raise PathBlockedError(f"Доступ к {path} запрещён (системный/служебный каталог)")


def _search_roots() -> list[Path]:
    """Домашняя папка пользователя плюс корни остальных дисков (кроме системного C:)."""
    home = Path.home()
    roots = [home]
    system_drive = Path(home.anchor)
    for letter in string.ascii_uppercase:
        drive = Path(f"{letter}:/")
        if drive.exists() and drive != system_drive:
            roots.append(drive)
    return roots


class FileManager:
    def __init__(self, config: dict):
        files_config = (config or {}).get("files") or {}
        self.max_search_seconds = float(files_config.get("max_search_seconds", 8))
        self.max_search_results = int(files_config.get("max_search_results", 5))
        self.max_read_chars = int(files_config.get("max_read_chars", 4000))

    def find_files(self, query: str) -> list[Path]:
        """Ищет файлы, в имени которых встречается query (без учёта регистра).

        Сначала проверяет типичные пользовательские папки (Рабочий стол, Документы и
        т.п.) — в подавляющем большинстве случаев нужный файл там. Только если ничего не
        нашлось, расширяет поиск на всю домашнюю папку и остальные диски, укладываясь в
        общий таймаут."""
        query_lower = query.lower()
        deadline = time.monotonic() + self.max_search_seconds
        home = Path.home()

        priority_dirs = [home / name for name in _PRIORITY_DIR_NAMES if (home / name).is_dir()]
        matches = self._walk_for_matches(priority_dirs, query_lower, deadline)
        if matches:
            return matches[: self.max_search_results]

        already_covered = {d.name.lower() for d in priority_dirs}
        matches = self._walk_for_matches(
            _search_roots(), query_lower, deadline, skip_top_level=already_covered
        )
        return matches[: self.max_search_results]

    def _walk_for_matches(
        self, roots: list[Path], query_lower: str, deadline: float,
        skip_top_level: set[str] | None = None,
    ) -> list[Path]:
        matches: list[Path] = []
        for root in roots:
            if not root.is_dir():
                continue
            for dirpath, dirnames, filenames in os.walk(root):
                if time.monotonic() > deadline:
                    logger.info("Поиск остановлен по таймауту (%ss)", self.max_search_seconds)
                    return matches

                if skip_top_level and Path(dirpath) == root:
                    # Эти подпапки уже проверены отдельно на предыдущем шаге — не дублируем обход
                    dirnames[:] = [d for d in dirnames if d.lower() not in skip_top_level]

                dirnames[:] = [
                    d for d in dirnames
                    if d.lower() not in _BLOCKED_DIR_NAMES and not d.startswith(".")
                ]

                for name in filenames:
                    if query_lower in name.lower():
                        matches.append(Path(dirpath) / name)
                        if len(matches) >= self.max_search_results:
                            return matches
        return matches

    def open_file(self, path: Path) -> None:
        _assert_allowed(path)
        os.startfile(str(path))  # noqa: S606 — Windows-only запуск ассоциированным приложением

    def read_text(self, path: Path) -> str:
        _assert_allowed(path)
        text = path.read_text(encoding="utf-8", errors="ignore")
        return text[: self.max_read_chars]

    def create_file(self, path: Path, content: str = "") -> None:
        _assert_allowed(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    def create_folder(self, path: Path) -> None:
        _assert_allowed(path)
        path.mkdir(parents=True, exist_ok=True)
