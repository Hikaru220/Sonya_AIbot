# Соня — локальный голосовой ассистент

Голосовой ассистент по триггер-слову ("Соня, ...") с распознаванием речи, пониманием
команд через Gemini API, выполнением действий (запуск игр/программ) и голосовым ответом.
Адаптируется под текущую нагрузку GPU и засыпает при простое.

Подробное техническое задание: [TOR.md](TOR.md)

## Статус

🚧 В разработке — v0.1 (ядро: wake word → STT → brain → executor → TTS).

## Стек

Python 3.11+, Vosk, faster-whisper, Gemini API, Silero TTS, pynvml/psutil.

## Быстрый старт

```bash
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env   # заполнить GEMINI_API_KEY (и остальные ключи по желанию)
python main.py
```

Голосовой триггер "Соня" требует модель Vosk — без неё работает ручной запуск по Enter
в консоли. Скачивается напрямую, без регистрации (~45 МБ):

```bash
curl -L -o models/vosk/vosk-model-small-ru.zip https://alphacephei.com/vosk/models/vosk-model-small-ru-0.22.zip
cd models/vosk && unzip vosk-model-small-ru.zip && mv vosk-model-small-ru-0.22 model && rm vosk-model-small-ru.zip
```

## Структура проекта

```
sona/
  wake_word/        триггер-слово "Соня"
  stt/               распознавание речи (адаптивно GPU/CPU)
  brain/             интеграция с Gemini — разбор команд
  executor/          выполнение действий (запуск программ, погода, поиск, файлы)
  files/             доступ к файлам (поиск/открытие/чтение/создание), системные
                      папки заблокированы
  tts/               синтез речи
  avatar/            (v0.3) визуальный аватар через VTube Studio
  resource_monitor/  мониторинг нагрузки GPU/CPU
  power/             сон при простое
  orchestrator/      главный цикл
config/              конфиги и алиасы программ
```
