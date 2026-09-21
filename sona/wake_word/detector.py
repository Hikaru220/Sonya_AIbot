"""Детектор кодового слова: слушает микрофон и блокирует поток до срабатывания триггера.

Движок — Vosk: маленькая офлайн-модель распознавания речи (~50 МБ, без регистрации,
скачивается напрямую с alphacephei.com/vosk/models). Вместо отдельного бинарного
классификатора слушаем поток текста и ищем в нём кодовые слова — это даёт нативную
поддержку кириллицы "Соня"/"Сонечка" без транслитерации на английский.
"""

import json
import logging
from pathlib import Path

logger = logging.getLogger("sona.wake_word")

# Намеренно относительный путь (от рабочей директории, как и остальные конфиги в
# проекте): абсолютный путь здесь ломает Vosk на Windows, если в пути есть кириллица
# (как в имени этой папки) — его C++-библиотека не может открыть такой путь.
_MODEL_DIR = Path("models/vosk/model")
_SAMPLE_RATE = 16000
_BLOCK_SIZE = 4000  # 0.25 сек при 16kHz — баланс отзывчивости и нагрузки на CPU


class WakeWordDetector:
    def __init__(self, config: dict):
        ww_config = config.get("wake_word", {}) if config else {}
        self.keywords = [k.lower() for k in ww_config.get("keywords", ["соня", "сонечка"])]

        self._model = None  # кэш Vosk Model, конструктор дорогой (грузит с диска)
        if not _MODEL_DIR.is_dir():
            # TODO: скачать модель (см. README) и распаковать в models/vosk/model/
            logger.warning(
                "Модель Vosk не найдена по пути '%s'. Пока использую временную "
                "заглушку — нажатие Enter в консоли будет имитировать срабатывание "
                "триггер-слова.",
                _MODEL_DIR,
            )

    def listen_for_wake_word(self) -> None:
        """Блокирует вызывающий поток, пока не будет обнаружено триггер-слово."""
        if not _MODEL_DIR.is_dir():
            self._listen_fallback_manual()
        else:
            self._listen_vosk()

    def _listen_fallback_manual(self) -> None:
        """Заглушка на время отсутствия модели: Enter в консоли = триггер-слово."""
        logger.info("Жду триггер-слово (заглушка: нажмите Enter в консоли)...")
        input()
        logger.info("Триггер-слово 'обнаружено' (ручной ввод через Enter)")

    def _get_model(self):
        if self._model is None:
            from vosk import Model
            self._model = Model(str(_MODEL_DIR))
        return self._model

    def _contains_keyword(self, text: str) -> str | None:
        text = text.lower()
        for keyword in self.keywords:
            if keyword in text:
                return keyword
        return None

    def _listen_vosk(self) -> None:
        """Слушает микрофон через sounddevice и проверяет распознанный текст на
        наличие кодовых слов — по промежуточным (partial) результатам, для быстрой
        реакции, не дожидаясь паузы в речи."""
        import sounddevice as sd
        from vosk import KaldiRecognizer

        recognizer = KaldiRecognizer(self._get_model(), _SAMPLE_RATE)

        logger.info("Жду триггер-слово (%s)...", ", ".join(self.keywords))

        with sd.RawInputStream(
            samplerate=_SAMPLE_RATE,
            channels=1,
            dtype="int16",
            blocksize=_BLOCK_SIZE,
        ) as stream:
            while True:
                data, _overflowed = stream.read(_BLOCK_SIZE)
                data = bytes(data)

                if recognizer.AcceptWaveform(data):
                    text = json.loads(recognizer.Result()).get("text", "")
                else:
                    text = json.loads(recognizer.PartialResult()).get("partial", "")

                found = self._contains_keyword(text)
                if found:
                    logger.info("Триггер-слово обнаружено: %s (текст: %r)", found, text)
                    recognizer.Reset()
                    return
