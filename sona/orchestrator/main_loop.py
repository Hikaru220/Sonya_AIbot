"""Главный цикл ассистента "Соня": wake word -> STT -> brain -> executor -> TTS.

Контракты модулей (реализуются в соответствующих пакетах):

  ResourceMonitor(config).get_device() -> "cuda" | "cpu"

  WakeWordDetector(config)
    .listen_for_wake_word() -> None   # блокирует поток, пока не услышит триггер-слово

  Transcriber(config, resource_monitor)
    .record_and_transcribe(max_seconds: float = 6.0) -> str   # текст команды

  GeminiBrain(config)
    .parse_command(text: str) -> dict
      # {"action": "launch_app" | "get_weather" | "answer_question" | "web_search" | "unknown",
      #  "target": "<строка или null>", "reply": "Да, хозяин, ..."}

  ActionExecutor(config)
    .execute(intent: dict) -> str   # финальная фраза для озвучки

  Speaker(config, resource_monitor)
    .speak(text: str) -> None

  IdleManager(timeout_seconds).reset() / .is_idle()
"""

import logging
import threading
import time

from sona.brain.gemini_brain import GeminiBrain
from sona.executor.action_executor import ActionExecutor
from sona.power.idle_manager import IdleManager
from sona.resource_monitor.monitor import ResourceMonitor
from sona.stt.transcriber import Transcriber
from sona.tts.speaker import Speaker
from sona.wake_word.detector import WakeWordDetector

log = logging.getLogger("sona.orchestrator")


class Orchestrator:
    def __init__(self, config: dict):
        self.config = config
        self.resource_monitor = ResourceMonitor(config)
        self.idle_manager = IdleManager(config["power"]["idle_timeout_seconds"])

        self.wake_word = WakeWordDetector(config)
        self.brain = GeminiBrain(config)
        self.executor = ActionExecutor(config)

        # STT/TTS выгружаются при простое, поэтому создаются лениво
        self._transcriber: Transcriber | None = None
        self._speaker: Speaker | None = None
        self._lock = threading.Lock()

    def _ensure_hot_modules(self) -> None:
        with self._lock:
            if self._transcriber is None:
                log.info("Загружаю STT/TTS модели...")
                self._transcriber = Transcriber(self.config, self.resource_monitor)
                self._speaker = Speaker(self.config, self.resource_monitor)

    def _unload_hot_modules(self) -> None:
        with self._lock:
            if self._transcriber is not None:
                log.info("Простой %ss — выгружаю STT/TTS из памяти",
                          self.config["power"]["idle_timeout_seconds"])
                self._transcriber = None
                self._speaker = None

    def _handle_command(self) -> None:
        self._ensure_hot_modules()
        # Сбрасываем таймер сразу, а не в конце: пока команда обрабатывается (запись,
        # STT, Gemini, TTS — секунды), watchdog не должен считать нас простаивающими и
        # выгружать self._transcriber/self._speaker прямо во время их использования.
        self.idle_manager.reset()

        text = self._transcriber.record_and_transcribe()
        if not text.strip():
            log.info("Пустая команда, пропускаю")
            return

        log.info("Команда: %s", text)
        intent = self.brain.parse_command(text)
        reply = self.executor.execute(intent)
        self._speaker.speak(reply)
        self.idle_manager.reset()

    def run(self) -> None:
        log.info("Соня запущена. Жду триггер-слово...")
        while True:
            try:
                self.wake_word.listen_for_wake_word()
                self._handle_command()
            except Exception:
                log.exception("Ошибка при ожидании триггер-слова или обработке команды")

            if self.idle_manager.is_idle():
                self._unload_hot_modules()

    def run_with_idle_watchdog(self) -> None:
        """Запускает run() и параллельно следит за простоем, чтобы выгружать модели
        даже если долго не было ни одного wake word после последней команды."""
        def watchdog():
            while True:
                time.sleep(30)
                if self.idle_manager.is_idle():
                    self._unload_hot_modules()

        threading.Thread(target=watchdog, daemon=True).start()
        self.run()
