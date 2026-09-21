"""Распознавание речи: запись с микрофона с авто-остановкой по тишине + faster-whisper."""

import logging

import numpy as np
import sounddevice as sd
from faster_whisper import WhisperModel

logger = logging.getLogger("sona.stt")

SAMPLE_RATE = 16000
CHUNK_SECONDS = 0.15  # длительность одного блока записи, используемого для анализа тишины
SILENCE_RMS_THRESHOLD = 500  # порог амплитуды (RMS по int16-семплам) — ниже считается тишиной
SILENCE_HOLD_SECONDS = 1.2  # сколько тишины подряд ждём после начала речи перед остановкой


class Transcriber:
    def __init__(self, config: dict, resource_monitor):
        self.resource_monitor = resource_monitor

        stt_config = config["stt"]
        self.model_size = stt_config["model_size"]
        self.language = stt_config["language"]

        # Модели faster-whisper кэшируются по устройству (cuda/cpu), чтобы не перегружать
        # веса на каждый вызов. Само устройство при этом выбирается заново в каждом
        # record_and_transcribe, т.к. resource_monitor может отдать другой ответ в
        # зависимости от текущей загрузки GPU (например, если запустили тяжёлую игру).
        self._models: dict[str, WhisperModel] = {}

    def _get_model(self, device: str) -> WhisperModel:
        model = self._models.get(device)
        if model is None:
            compute_type = "float16" if device == "cuda" else "int8"
            logger.info(
                "Загружаю модель faster-whisper '%s' на устройстве %s (compute_type=%s)",
                self.model_size, device, compute_type,
            )
            model = WhisperModel(self.model_size, device=device, compute_type=compute_type)
            self._models[device] = model
        return model

    def _record_with_silence_detection(self, max_seconds: float) -> np.ndarray | None:
        """Пишет аудио блоками по CHUNK_SECONDS, пока не наступит тишина после речи или
        не истечёт max_seconds. Возвращает моно float32-массив либо None, если речи не было
        вовсе (только тишина)."""
        chunk_frames = max(1, int(SAMPLE_RATE * CHUNK_SECONDS))
        max_chunks = max(1, round(max_seconds / CHUNK_SECONDS))
        silence_hold_chunks = max(1, round(SILENCE_HOLD_SECONDS / CHUNK_SECONDS))

        chunks: list[np.ndarray] = []
        speech_detected = False
        silence_run = 0

        # Примечание: тишина определяется простым порогом по амплитуде (RMS int16) — этого
        # достаточно для v0.1. Полноценный VAD (например, webrtcvad или silero-vad) точнее
        # отличал бы речь от шума и стоит его добавить на следующих этапах.
        with sd.InputStream(samplerate=SAMPLE_RATE, channels=1, dtype="int16") as stream:
            for _ in range(max_chunks):
                block, _overflowed = stream.read(chunk_frames)
                chunks.append(block.copy())

                rms = float(np.sqrt(np.mean(block.astype(np.float64) ** 2)))
                if rms >= SILENCE_RMS_THRESHOLD:
                    speech_detected = True
                    silence_run = 0
                else:
                    silence_run += 1

                if speech_detected and silence_run >= silence_hold_chunks:
                    logger.info("Обнаружена тишина после речи, останавливаю запись")
                    break
            else:
                logger.info("Достигнут предел max_seconds=%s, останавливаю запись", max_seconds)

        if not speech_detected:
            return None

        audio_int16 = np.concatenate(chunks, axis=0).flatten()
        return audio_int16.astype(np.float32) / 32768.0

    def record_and_transcribe(self, max_seconds: float = 6.0) -> str:
        """Записывает аудио с микрофона по умолчанию (останавливаясь раньше при тишине),
        распознаёт его и возвращает текст."""
        logger.info("Начинаю запись команды (max_seconds=%s)", max_seconds)
        audio = self._record_with_silence_detection(max_seconds)
        if audio is None or audio.size == 0:
            logger.info("За всё время записи была только тишина, распознавание пропущено")
            return ""

        device = self.resource_monitor.get_device()
        model = self._get_model(device)
        segments, _info = model.transcribe(audio, language=self.language)
        text = "".join(segment.text for segment in segments).strip()

        logger.info("Распознанный текст: %s", text)
        return text
