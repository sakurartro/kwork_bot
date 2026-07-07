"""
Точка входа Telegram-бота Kwork Радар.

Запуск:
    ./venv/bin/python run_bot.py

Требует в .env: TELEGRAM_BOT_TOKEN, TELEGRAM_OWNER_ID, GEMINI_API_KEY.
"""

from __future__ import annotations

import asyncio

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from loguru import logger

from config.settings import get_settings
from src.ai.gemini_client import GeminiClient
from src.bot.handlers import router, state
from src.parser.session import KworkSession
from src.storage.database import Database
from src.utils.logger import setup_logging


async def main() -> None:
    settings = get_settings()
    setup_logging(settings.log_level)

    if not settings.telegram_bot_token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN не задан в .env")
    if not settings.telegram_owner_id:
        raise RuntimeError("TELEGRAM_OWNER_ID не задан в .env — бот отвечает только владельцу")
    if not settings.gemini_api_key:
        raise RuntimeError("GEMINI_API_KEY не задан в .env")

    state.session = KworkSession()
    state.gemini = GeminiClient(api_key=settings.gemini_api_key, model=settings.gemini_model)
    state.db = Database(settings.db_path)
    await state.db.connect()

    bot = Bot(token=settings.telegram_bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher()
    dp.include_router(router)

    logger.info("Kwork-бот запущен, ждём /start от владельца {}", settings.telegram_owner_id)
    try:
        await dp.start_polling(bot)
    finally:
        state.running = False
        if state.polling_task is not None:
            state.polling_task.cancel()
        if state.session is not None:
            await state.session.aclose()
        if state.gemini is not None:
            await state.gemini.aclose()
        if state.db is not None:
            await state.db.close()


if __name__ == "__main__":
    asyncio.run(main())
