"""Определяет, свободен ли GPU (по загрузке VRAM), чтобы выбирать устройство для STT/TTS: cuda или cpu."""

import logging
import time

logger = logging.getLogger("sona.resource_monitor")


class ResourceMonitor:
    def __init__(self, config: dict):
        rm_config = config.get("resource_monitor", {}) if config else {}
        self.threshold_percent = rm_config.get("gpu_load_threshold_percent", 75)
        self.poll_interval_seconds = rm_config.get("poll_interval_seconds", 2)

        self._last_result = None
        self._last_check_time = 0.0

        self._cuda_available = False
        try:
            import torch

            self._cuda_available = bool(torch.cuda.is_available())
        except Exception as exc:
            logger.warning("torch недоступен или torch.cuda.is_available() упал: %s", exc)
            self._cuda_available = False

        self._nvml_available = False
        self._pynvml = None
        if self._cuda_available:
            try:
                import pynvml

                pynvml.nvmlInit()
                self._pynvml = pynvml
                self._nvml_available = True
            except Exception as exc:
                logger.warning("Не удалось инициализировать pynvml: %s", exc)
                self._nvml_available = False

    def _get_gpu_vram_percent(self):
        """Возвращает процент занятой VRAM на устройстве 0, либо None при ошибке."""
        if not self._nvml_available or self._pynvml is None:
            return None
        try:
            handle = self._pynvml.nvmlDeviceGetHandleByIndex(0)
            mem_info = self._pynvml.nvmlDeviceGetMemoryInfo(handle)
            if mem_info.total == 0:
                return None
            return (mem_info.used / mem_info.total) * 100
        except Exception as exc:
            logger.warning("Ошибка при опросе pynvml: %s", exc)
            return None

    def get_device(self) -> str:
        """Возвращает "cuda" или "cpu" в зависимости от текущей загрузки GPU."""
        if not self._cuda_available or not self._nvml_available:
            return "cpu"

        now = time.monotonic()
        if self._last_result is not None and (now - self._last_check_time) < self.poll_interval_seconds:
            return self._last_result

        vram_percent = self._get_gpu_vram_percent()
        if vram_percent is None:
            result = "cpu"
        elif vram_percent >= self.threshold_percent:
            result = "cpu"
        else:
            result = "cuda"

        self._last_result = result
        self._last_check_time = now
        return result
