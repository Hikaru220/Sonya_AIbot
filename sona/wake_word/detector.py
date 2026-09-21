"""Детектор кодового слова: слушает микрофон и блокирует поток до срабатывания триггера."""

import logging
from pathlib import Path

logger = logging.getLogger("sona.wake_word")

_SAMPLE_RATE = 16000
_CHUNK_SAMPLES = 1280  # 80 мс при 16 kHz — размер чанка, который ожидает openWakeWord

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_MODEL_DIR = _PROJECT_ROOT / "models" / "wakeword"
_MODEL_EXTENSIONS = (".onnx", ".tflite")


class WakeWordDetector:
    def __init__(self, config: dict):
        ww_config = config.get("wake_word", {}) if config else {}
        self.keyword = ww_config.get("keyword", "sona")
        self.threshold = float(ww_config.get("threshold", 0.5))

        self._model_path = self._find_model_path()
        self._loaded_model = None  # кэш openWakeWord Model, чтобы не грузить с диска на каждый цикл
        if self._model_path is None:
            # TODO: обучить или скачать кастомную модель openWakeWord под слово "Соня" —
            # готовой предобученной модели для этого слова не существует, это отдельная
            # задача. Файл нужно положить в models/wakeword/{keyword}.onnx (или .tflite),
            # после чего заглушка ниже перестанет использоваться автоматически.
            logger.warning(
                "Модель wake-word не найдена: ожидался файл '%s' или '%s'. "
                "Пока использую временную заглушку — нажатие Enter в консоли будет "
                "имитировать срабатывание триггер-слова, чтобы можно было тестировать "
                "остальной пайплайн без обученной модели.",
                _MODEL_DIR / f"{self.keyword}.onnx",
                _MODEL_DIR / f"{self.keyword}.tflite",
            )

    def _find_model_path(self) -> Path | None:
        """Ищет файл модели models/wakeword/{keyword}.onnx или .tflite."""
        for ext in _MODEL_EXTENSIONS:
            candidate = _MODEL_DIR / f"{self.keyword}{ext}"
            if candidate.is_file():
                return candidate
        return None

    def listen_for_wake_word(self) -> None:
        """Блокирует вызывающий поток, пока не будет обнаружено триггер-слово."""
        if self._model_path is None:
            self._listen_fallback_manual()
        else:
            self._listen_openwakeword()

    def _listen_fallback_manual(self) -> None:
        """Заглушка на время отсутствия обученной модели: Enter в консоли = триггер-слово."""
        logger.info("Жду триггер-слово (заглушка: нажмите Enter в консоли)...")
        input()
        logger.info("Триггер-слово 'обнаружено' (ручной ввод через Enter)")

    def _get_model(self):
        """Лениво загружает и кэширует Model — конструктор дорогой (диск + инициализация
        ONNX-рантайма), а слушаем мы в цикле на каждый wake word, поэтому грузим один раз."""
        if self._loaded_model is None:
            from openwakeword.model import Model
            self._loaded_model = Model(wakeword_models=[str(self._model_path)])
        return self._loaded_model

    def _listen_openwakeword(self) -> None:
        """Слушает микрофон через sounddevice и прогоняет чанки аудио через openWakeWord."""
        import sounddevice as sd

        model = self._get_model()

        logger.info(
            "Жду триггер-слово '%s' (модель: %s, порог: %.2f)...",
            self.keyword, self._model_path.name, self.threshold,
        )

        with sd.InputStream(
            samplerate=_SAMPLE_RATE,
            channels=1,
            dtype="int16",
            blocksize=_CHUNK_SAMPLES,
        ) as stream:
            while True:
                audio_chunk, _overflowed = stream.read(_CHUNK_SAMPLES)
                predictions = model.predict(audio_chunk.flatten())

                triggered = [
                    (name, score) for name, score in predictions.items()
                    if score >= self.threshold
                ]
                if triggered:
                    name, score = max(triggered, key=lambda item: item[1])
                    logger.info("Триггер-слово обнаружено: %s (score=%.2f)", name, score)
                    return
