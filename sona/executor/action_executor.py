"""Исполнитель действий: запуск программ по алиасам из конфига, погода, ответы на вопросы."""

import logging
import os
import subprocess

import requests

from sona.config.app_aliases import DEFAULT_ALIASES_FILE, load_app_aliases

logger = logging.getLogger("sona.executor")

# Бесплатный сервис без ключа и лимитов для личного использования.
GEOCODING_URL = "https://geocoding-api.open-meteo.com/v1/search"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"

# Search API для вопросов про свежие/актуальные события — бесплатный тариф с ключом
# (TAVILY_API_KEY в .env), см. tavily.com.
TAVILY_SEARCH_URL = "https://api.tavily.com/search"

# Коды погоды WMO (https://open-meteo.com/en/docs) -> короткое русское описание.
WEATHER_CODE_DESCRIPTIONS = {
    0: "ясно", 1: "преимущественно ясно", 2: "переменная облачность", 3: "пасмурно",
    45: "туман", 48: "изморозь",
    51: "лёгкая морось", 53: "морось", 55: "сильная морось",
    61: "небольшой дождь", 63: "дождь", 65: "сильный дождь",
    71: "небольшой снег", 73: "снег", 75: "сильный снегопад",
    80: "ливень", 81: "сильный ливень", 82: "очень сильный ливень",
    95: "гроза", 96: "гроза с градом", 99: "сильная гроза с градом",
}


class ActionExecutor:
    def __init__(self, config: dict):
        self.config = config
        executor_config = config.get("executor") or {}
        aliases_file = executor_config.get("aliases_file", DEFAULT_ALIASES_FILE)
        self.apps = self._load_apps(aliases_file)

    def _load_apps(self, aliases_file: str) -> dict[str, str]:
        """Строит словарь app_key -> путь к исполняемому файлу из общего загрузчика алиасов."""
        apps = {}
        for app_key, app_info in load_app_aliases(aliases_file).items():
            path = app_info.get("path")
            if path:
                apps[app_key] = path
            else:
                logger.warning("В %s у программы %r не указан path, пропускаю её", aliases_file, app_key)
        return apps

    def execute(self, intent: dict) -> str:
        """Выполняет intent от GeminiBrain.parse_command и возвращает фразу для озвучки. Исключения наружу не пробрасывает."""
        try:
            action = intent.get("action")

            if action == "launch_app":
                return self._launch_app(intent)
            if action == "get_weather":
                return self._get_weather(intent)
            if action == "web_search":
                return self._web_search(intent)
            if action == "answer_question":
                # Gemini уже сформулировал ответ (математика, факты и т.п.) — просто озвучиваем
                return intent.get("reply") or "Да, хозяин, не поняла вопрос"

            # action == "unknown" (или любое другое/отсутствующее значение) — действовать не нужно.
            # `or`, а не .get(..., default): GeminiBrain всегда проставляет ключ "reply" (пусть
            # даже пустой строкой), поэтому .get() с дефолтом тут никогда бы не сработал.
            return intent.get("reply") or "Да, хозяин, не поняла команду"

        except Exception:
            # Последний рубеж: сбой executor'а не должен ронять весь оркестратор
            logger.exception("Непредвиденная ошибка при выполнении intent: %r", intent)
            return "Да, хозяин, что-то пошло не так"

    def _launch_app(self, intent: dict) -> str:
        target = intent.get("target")
        path = self.apps.get(target)

        if path is None:
            logger.warning("Не нашла программу по ключу %r среди известных алиасов", target)
            return "Да, хозяин, не нашла такую программу"

        try:
            # shell=True не используем: путь передаём напрямую первым элементом списка
            subprocess.Popen([path])
        except OSError as exc:
            # Сюда попадает и FileNotFoundError, если .exe по пути из конфига не существует
            logger.error("Не удалось запустить %r по пути %s: %s", target, path, exc)
            return "Да, хозяин, не получилось запустить — кажется, программы нет по этому пути"

        return intent.get("reply") or "Да, хозяин, запускаю"

    def _get_weather(self, intent: dict) -> str:
        """target — название города (желательно на английском/латиницей от Gemini для
        надёжного геокодинга); реальные данные берём с бесплатного Open-Meteo."""
        city = intent.get("target")
        if not city:
            return "Да, хозяин, не поняла для какого города нужна погода"

        try:
            geo_resp = requests.get(
                GEOCODING_URL,
                params={"name": city, "count": 1, "language": "ru"},
                timeout=5,
            )
            geo_resp.raise_for_status()
            geo_results = (geo_resp.json() or {}).get("results")

            if not geo_results:
                logger.warning("Geocoding не нашёл город %r", city)
                return f"Да, хозяин, не нашла город {city}"

            place = geo_results[0]
            lat, lon = place["latitude"], place["longitude"]
            place_name = place.get("name", city)

            forecast_resp = requests.get(
                FORECAST_URL,
                params={"latitude": lat, "longitude": lon, "current_weather": "true"},
                timeout=5,
            )
            forecast_resp.raise_for_status()
            current = (forecast_resp.json() or {}).get("current_weather") or {}

            temperature = current.get("temperature")
            weather_code = current.get("weathercode")
            description = WEATHER_CODE_DESCRIPTIONS.get(weather_code, "")

            if temperature is None:
                return f"Да, хозяин, не удалось получить погоду для {place_name}"

            reply = f"Да, хозяин, в городе {place_name} сейчас {temperature:g}°C"
            if description:
                reply += f", {description}"
            return reply

        except requests.RequestException as exc:
            logger.error("Ошибка запроса погоды для %r: %s", city, exc)
            return "Да, хозяин, не получилось узнать погоду — проблема с интернетом"

    def _web_search(self, intent: dict) -> str:
        """target — короткий поисковый запрос от Gemini; ищем через Tavily (бесплатный
        ключ, до ~1000 запросов/мес) и просим сразу синтезированный краткий ответ."""
        query = intent.get("target")
        if not query:
            return "Да, хозяин, не поняла что искать"

        api_key = os.environ.get("TAVILY_API_KEY")
        if not api_key:
            logger.warning("TAVILY_API_KEY не задан в .env — web_search недоступен")
            return "Да, хозяин, поиск в интернете пока не настроен — нет ключа Tavily"

        try:
            resp = requests.post(
                TAVILY_SEARCH_URL,
                json={
                    "api_key": api_key,
                    "query": query,
                    "search_depth": "basic",
                    "include_answer": True,
                    "max_results": 3,
                },
                timeout=8,
            )
            resp.raise_for_status()
            data = resp.json() or {}

            answer = data.get("answer")
            if answer:
                return f"Да, хозяин, {answer}"

            # Если синтезированного ответа нет — берём заголовок/сниппет первого результата
            results = data.get("results") or []
            if results:
                snippet = results[0].get("content") or results[0].get("title")
                if snippet:
                    return f"Да, хозяин, вот что нашла: {snippet}"

            return "Да, хозяин, ничего не нашла по этому запросу"

        except requests.RequestException as exc:
            logger.error("Ошибка запроса к Tavily для %r: %s", query, exc)
            return "Да, хозяин, не получилось поискать в интернете — проблема с сетью"
