"""Отслеживание простоя ассистента: сброс таймера при активности, сон при тишине."""

import time


class IdleManager:
    def __init__(self, timeout_seconds: int):
        self.timeout_seconds = timeout_seconds
        self._last_activity = time.monotonic()

    def reset(self) -> None:
        """Вызывается после каждой обработанной команды."""
        self._last_activity = time.monotonic()

    def is_idle(self) -> bool:
        return (time.monotonic() - self._last_activity) >= self.timeout_seconds
