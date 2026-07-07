"""
Точка входа для локального тестового сервера парсера Kwork (без Telegram).

Запуск:
    ./venv/bin/python run_web.py

Открыть в браузере:
    http://127.0.0.1:8000
"""

import uvicorn

from config.settings import get_settings

if __name__ == "__main__":
    settings = get_settings()
    uvicorn.run("src.web.app:app", host=settings.web_host, port=settings.web_port, reload=True)
