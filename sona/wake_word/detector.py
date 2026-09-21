"""Детектор кодового слова: слушает микрофон и блокирует поток до срабатывания триггера.

Движок — Picovoice Porcupine: модели (.ppn) генерируются мгновенно на
console.picovoice.ai по тексту фразы, без обучения и без GPU. Бесплатно для
личного некоммерческого использования.
"""

import logging
import os
import struct
from pathlib import Path

logger = logging.getLogger("sona.wake_word")

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_MODEL_DIR = _PROJECT_ROOT / "models" / "wakeword"


class WakeWordDetector:
    def __init__(self, config: dict):
        ww_config = config.get("wake_word", {}) if config else {}
        self.keywords = ww_config.get("keywords", ["sonya", "sonechka"])
        self.sensitivity = float(ww_config.get("sensitivity", 0.5))

        self._access_key = os.environ.get("PICOVOICE_ACCESS_KEY")
        self._keyword_paths = self._find_keyword_paths()
        self._porcupine = None  # кэш инстанса Porcupine, конструктор дорогой

        if not self._keyword_paths or not self._access_key:
            # TODO: создать .ppn-файлы на console.picovoice.ai (платформа Windows) для
            # каждого слова из self.keywords, положить в models/wakeword/{keyword}.ppn,
            # и добавить PICOVOICE_ACCESS_KEY в .env (ключ там же, в консоли).
            logger.warning(
                "Модели Porcupine (.ppn) в '%s' или PICOVOICE_ACCESS_KEY в .env не "
                "найдены. Пока использую временную заглушку — нажатие Enter в консоли "
                "будет имитировать срабатывание триггер-слова.",
                _MODEL_DIR,
            )

    def _find_keyword_paths(self) -> list[str]:
        """Ищет models/wakeword/{keyword}.ppn для каждого слова; пропускает отсутствующие."""
        paths = []
        for keyword in self.keywords:
            candidate = _MODEL_DIR / f"{keyword}.ppn"
            if candidate.is_file():
                paths.append(str(candidate))
            else:
                logger.warning("Не найден файл модели Porcupine для %r: %s", keyword, candidate)
        return paths

    def listen_for_wake_word(self) -> None:
        """Блокирует вызывающий поток, пока не будет обнаружено триггер-слово."""
        if not self._keyword_paths or not self._access_key:
            self._listen_fallback_manual()
        else:
            self._listen_porcupine()

    def _listen_fallback_manual(self) -> None:
        """Заглушка на время отсутствия ключа/моделей: Enter в консоли = триггер-слово."""
        logger.info("Жду триггер-слово (заглушка: нажмите Enter в консоли)...")
        input()
        logger.info("Триггер-слово 'обнаружено' (ручной ввод через Enter)")

    def _get_porcupine(self):
        if self._porcupine is None:
            import pvporcupine
            sensitivities = [self.sensitivity] * len(self._keyword_paths)
            self._porcupine = pvporcupine.create(
                access_key=self._access_key,
                keyword_paths=self._keyword_paths,
                sensitivities=sensitivities,
            )
        return self._porcupine

    def _listen_porcupine(self) -> None:
        """Слушает микрофон через sounddevice и прогоняет кадры через Porcupine."""
        import sounddevice as sd

        porcupine = self._get_porcupine()

        logger.info("Жду триггер-слово (%s)...", ", ".join(self.keywords))

        with sd.RawInputStream(
            samplerate=porcupine.sample_rate,
            channels=1,
            dtype="int16",
            blocksize=porcupine.frame_length,
        ) as stream:
            while True:
                data, _overflowed = stream.read(porcupine.frame_length)
                pcm = struct.unpack_from("h" * porcupine.frame_length, data)
                keyword_index = porcupine.process(pcm)
                if keyword_index >= 0:
                    logger.info("Триггер-слово обнаружено: %s", self.keywords[keyword_index])
                    return
