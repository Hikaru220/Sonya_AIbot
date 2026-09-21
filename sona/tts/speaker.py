"""Синтез речи через Silero TTS (ru, v3) и воспроизведение через звуковую карту."""

import logging

import sounddevice
import torch

logger = logging.getLogger("sona.tts")


class Speaker:
    def __init__(self, config: dict, resource_monitor):
        self.resource_monitor = resource_monitor
        self._speaker_name = config["tts"]["speaker"]
        self._sample_rate = config["tts"]["sample_rate"]
        self._models = {}  # кэш загруженных моделей Silero по устройству: {"cuda": ..., "cpu": ...}

    def _get_model(self, device: str):
        """Возвращает модель Silero TTS для устройства, загружая и кэшируя её при первом обращении."""
        model = self._models.get(device)
        if model is None:
            logger.info("Загружаю модель Silero TTS (ru, v3_1_ru) на устройство %s", device)
            model, _ = torch.hub.load(
                "snakers4/silero-models",
                "silero_tts",
                language="ru",
                speaker="v3_1_ru",
            )
            model.to(device)
            self._models[device] = model
        return model

    def speak(self, text: str) -> None:
        """Синтезирует речь для русского текста и воспроизводит её через устройство
        вывода звука по умолчанию (блокирует поток до конца воспроизведения)."""
        if not text or not text.strip():
            return

        # Опрашиваем resource_monitor при каждом вызове (а не один раз в __init__),
        # чтобы TTS переезжал на CPU, если GPU занят игрой, и обратно, когда он освободится.
        device = self.resource_monitor.get_device()

        try:
            model = self._get_model(device)
            audio = model.apply_tts(text=text, speaker=self._speaker_name, sample_rate=self._sample_rate)

            # TODO (v0.2, см. TOR.md): прогнать audio через RVC-конвертацию поверх Silero
            # для более милого, человечного тембра. В v0.1 не реализуется — вне scope этого модуля.

            sounddevice.play(audio.numpy(), samplerate=self._sample_rate)
            sounddevice.wait()
        except Exception:
            logger.exception("Не удалось синтезировать или воспроизвести речь: %r", text)
            return
