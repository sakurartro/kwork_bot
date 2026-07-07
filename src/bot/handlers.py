"""Обработчики команд Telegram-бота.

/start — запустить фоновый цикл мониторинга биржи Kwork:
    1) собрать новые заказы (parser),
    2) отфильтровать уже виденные (storage, персистентно между перезапусками),
    3) классифицировать через Gemini — может ли Claude Code выполнить заказ
       полностью самостоятельно,
    4) если да — прислать владельцу карточку заказа (formatting) с кнопкой
       «Ответить заказчику» (см. cb_reply/handle_client_message ниже).

/stop — остановить цикл.

Доступ только для владельца (TELEGRAM_OWNER_ID) — фильтр на уровне роутера.
"""

from __future__ import annotations

import asyncio
from collections import OrderedDict
from html import escape

from aiogram import Bot, F, Router
from aiogram.filters import BaseFilter, Command
from aiogram.types import CallbackQuery, Message
from loguru import logger

from config.settings import get_settings
from src.ai.gemini_client import Classification, GeminiClient
from src.anti_block.delays import sleep_random
from src.bot.formatting import build_claude_prompt_messages, build_offer_draft_message, build_offer_message
from src.bot.keyboards import (
    CLAUDE_PROMPT_CALLBACK_PREFIX,
    OFFER_CALLBACK_PREFIX,
    REPLY_CALLBACK_PREFIX,
    build_order_keyboard,
)
from src.parser.kwork_parser import fetch_new_listings
from src.parser.models import Listing
from src.parser.session import KworkSession
from src.storage.database import Database
from src.utils.exceptions import GeminiError, KworkError

router = Router()

# Сколько последних одобренных заказов держим в памяти для кнопки «Ответить
# заказчику» — нужен доступ к title/description заказа по callback_data, а
# storage.Database их не хранит (там только id/title/url/status).
MAX_RECENT_LISTINGS = 200


class BotState:
    def __init__(self) -> None:
        self.session: KworkSession | None = None
        self.gemini: GeminiClient | None = None
        self.db: Database | None = None
        self.running: bool = False
        self.polling_task: asyncio.Task | None = None
        self.recent_listings: OrderedDict[int, Listing] = OrderedDict()
        # user_id -> listing_id, чей заказ ждёт вставленное сообщение заказчика
        self.pending_reply: dict[int, int] = {}

    def remember_listing(self, listing: Listing) -> None:
        self.recent_listings[listing.id] = listing
        self.recent_listings.move_to_end(listing.id)
        while len(self.recent_listings) > MAX_RECENT_LISTINGS:
            self.recent_listings.popitem(last=False)


state = BotState()


class OwnerFilter(BaseFilter):
    """Бот выполняет команды только от TELEGRAM_OWNER_ID — это личный
    инструмент одного человека, а не публичный бот. Работает и для сообщений,
    и для callback-кнопок — оба объекта отдают `.from_user`."""

    async def __call__(self, event: Message | CallbackQuery) -> bool:
        settings = get_settings()
        return (
            settings.telegram_owner_id is not None
            and event.from_user is not None
            and event.from_user.id == settings.telegram_owner_id
        )


router.message.filter(OwnerFilter())
router.callback_query.filter(OwnerFilter())


async def _monitor_loop(bot: Bot, owner_id: int) -> None:
    settings = get_settings()
    assert state.session is not None
    assert state.gemini is not None
    assert state.db is not None

    while state.running:
        try:
            listings, _ = await fetch_new_listings(state.session, pages=1)
        except KworkError as exc:
            logger.exception("Ошибка парсинга Kwork в фоновом цикле")
            await bot.send_message(owner_id, f"Ошибка парсинга Kwork: {exc}")
            await sleep_random(settings.parse_delay_min, settings.parse_delay_max)
            continue

        for listing in listings:
            if not state.running:
                break
            if await state.db.is_seen(listing.id):
                continue

            try:
                verdict = await state.gemini.classify(listing.title, listing.description)
            except GeminiError as exc:
                # Не отмечаем как seen — квота Gemini может освободиться, попробуем этот
                # заказ на следующем цикле, а не потеряем его молча навсегда.
                logger.warning("Gemini не смогла классифицировать заказ {}: {}", listing.id, exc)
                continue

            await state.db.mark_seen(
                listing.id,
                listing.title,
                listing.url,
                "approved" if verdict.can_be_done_by_ai else "rejected",
            )
            if verdict.can_be_done_by_ai:
                state.remember_listing(listing)
                await bot.send_message(
                    owner_id,
                    build_offer_message(listing, verdict),
                    reply_markup=build_order_keyboard(listing.id),
                )

        await sleep_random(settings.parse_delay_min, settings.parse_delay_max)


@router.message(Command("start"))
async def cmd_start(message: Message, bot: Bot) -> None:
    if state.polling_task is not None and not state.polling_task.done():
        await message.answer("Мониторинг уже запущен. /stop — остановить.")
        return

    assert message.from_user is not None
    state.running = True
    state.polling_task = asyncio.create_task(_monitor_loop(bot, message.from_user.id))
    await message.answer(
        "Запустил мониторинг биржи Kwork. Буду присылать заказы, которые Gemini "
        "одобрит как полностью выполнимые Claude Code без вашей помощи. /stop — остановить."
    )


@router.message(Command("stop"))
async def cmd_stop(message: Message) -> None:
    state.running = False
    if state.polling_task is not None:
        state.polling_task.cancel()
    await message.answer("Остановил мониторинг.")


@router.message(Command("testorder"))
async def cmd_testorder(message: Message) -> None:
    """Отладочная команда: присылает синтетическую карточку заказа с теми же
    кнопками, что и настоящий одобренный заказ — чтобы проверить «Ответить
    заказчику»/«Создать запрос» без ожидания реального заказа и без траты
    квоты Gemini на классификацию (сам classify() тут не вызывается)."""
    listing = Listing(
        id=999999999,
        title="[ТЕСТ] Написать скрипт на Python для парсинга Excel-таблицы",
        description=(
            "Нужен скрипт на Python: читает .xlsx, оставляет только строки, где "
            "столбец «Статус» = «Активен», сохраняет результат в новый файл. "
            "Результат — обычный .py-скрипт без графического интерфейса."
        ),
        url="https://kwork.ru/projects/999999999/view",
        budget="5 000 ₽",
        responses_count=0,
        posted_at=None,
        time_left="2 д.",
        author="ТестовыйЗаказчик",
    )
    verdict = Classification(
        can_be_done_by_ai=True,
        reason="Тестовая карточка — реальная классификация Gemini не выполнялась.",
    )
    state.remember_listing(listing)
    await message.answer(
        build_offer_message(listing, verdict),
        reply_markup=build_order_keyboard(listing.id),
    )


@router.callback_query(F.data.startswith(REPLY_CALLBACK_PREFIX))
async def cb_reply(callback: CallbackQuery) -> None:
    """Нажатие «Ответить заказчику» под карточкой заказа — переводит бота
    в режим ожидания: следующее текстовое сообщение владельца будет
    воспринято как сообщение заказчика (см. handle_client_message)."""
    assert callback.data is not None
    listing_id = int(callback.data.removeprefix(REPLY_CALLBACK_PREFIX))
    listing = state.recent_listings.get(listing_id)
    if listing is None:
        await callback.answer("Заказ устарел, кнопка недоступна.", show_alert=True)
        return

    assert callback.from_user is not None
    state.pending_reply[callback.from_user.id] = listing_id
    await callback.answer()
    if callback.message is not None:
        await callback.message.answer(
            f"Пришлите сообщение заказчика по заказу «{escape(listing.title)}» — "
            "сгенерирую живой ответ."
        )


@router.callback_query(F.data.startswith(OFFER_CALLBACK_PREFIX))
async def cb_offer(callback: CallbackQuery) -> None:
    """Нажатие «Создать запрос» под карточкой заказа — сразу генерирует
    черновик отклика (форма kwork.ru/new_offer) через Gemini, без ожидания
    дополнительного ввода от владельца."""
    assert callback.data is not None
    listing_id = int(callback.data.removeprefix(OFFER_CALLBACK_PREFIX))
    listing = state.recent_listings.get(listing_id)
    if listing is None:
        await callback.answer("Заказ устарел, кнопка недоступна.", show_alert=True)
        return

    await callback.answer("Генерирую черновик отклика…")
    if callback.message is None:
        return

    assert state.gemini is not None
    try:
        offer = await state.gemini.generate_offer(listing.title, listing.description, listing.budget)
    except GeminiError as exc:
        logger.warning("Gemini не смогла сгенерировать отклик для заказа {}: {}", listing_id, exc)
        await callback.message.answer(f"Не удалось сгенерировать отклик: {exc}")
        return

    await callback.message.answer(build_offer_draft_message(listing, offer))


@router.callback_query(F.data.startswith(CLAUDE_PROMPT_CALLBACK_PREFIX))
async def cb_claude_prompt(callback: CallbackQuery) -> None:
    """Нажатие «Промпт для Claude Code» под карточкой заказа — сразу генерирует
    максимально подробный технический промпт по ТЗ заказа (без ожидания
    дополнительного ввода). Длинный промпт может уйти несколькими сообщениями
    (см. build_claude_prompt_messages) — Telegram режет одно сообщение на 4096 символов."""
    assert callback.data is not None
    listing_id = int(callback.data.removeprefix(CLAUDE_PROMPT_CALLBACK_PREFIX))
    listing = state.recent_listings.get(listing_id)
    if listing is None:
        await callback.answer("Заказ устарел, кнопка недоступна.", show_alert=True)
        return

    await callback.answer("Генерирую промпт для Claude Code…")
    if callback.message is None:
        return

    assert state.gemini is not None
    try:
        prompt_text = await state.gemini.generate_claude_prompt(listing.title, listing.description)
    except GeminiError as exc:
        logger.warning("Gemini не смогла сгенерировать промпт для заказа {}: {}", listing_id, exc)
        await callback.message.answer(f"Не удалось сгенерировать промпт: {exc}")
        return

    for chunk in build_claude_prompt_messages(listing, prompt_text):
        await callback.message.answer(chunk)


@router.message(F.text)
async def handle_client_message(message: Message) -> None:
    """Текст, вставленный владельцем после нажатия «Ответить заказчику»,
    трактуется как сообщение заказчика — генерируем живой ответ через Gemini.
    Если кнопку не нажимали (нет pending_reply) — сообщение игнорируется."""
    assert message.from_user is not None
    listing_id = state.pending_reply.get(message.from_user.id)
    if listing_id is None:
        return

    listing = state.recent_listings.get(listing_id)
    if listing is None:
        state.pending_reply.pop(message.from_user.id, None)
        await message.answer("Заказ больше не доступен — начните заново по кнопке под новым заказом.")
        return

    assert state.gemini is not None
    assert message.text is not None
    try:
        reply = await state.gemini.generate_human_reply(listing.title, listing.description, message.text)
    except GeminiError as exc:
        logger.warning("Gemini не смогла сгенерировать ответ для заказа {}: {}", listing_id, exc)
        await message.answer(f"Не удалось сгенерировать ответ: {exc}")
        return

    state.pending_reply.pop(message.from_user.id, None)
    await message.answer(f"<pre>{escape(reply)}</pre>")
