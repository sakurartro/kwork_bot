"""Форматирование сообщений для Telegram (HTML parse mode)."""

from __future__ import annotations

from html import escape

from src.ai.gemini_client import Classification, Offer
from src.parser.models import Listing

MAX_DESCRIPTION_CHARS = 3000
# Запас от лимита сообщения Telegram (4096 символов) на HTML-эскейпинг/обёртку <pre> —
# режем длинный текст по этой границе, а не молча обрезаем его.
TELEGRAM_CHUNK_CHARS = 3000


def build_offer_message(listing: Listing, verdict: Classification) -> str:
    """Пакет по заказу, одобренному Gemini: все поля скопируемые/читаемые,
    описание — в <pre>, чтобы Telegram не пытался парсить его как HTML."""
    description = listing.description or "—"
    if len(description) > MAX_DESCRIPTION_CHARS:
        description = description[:MAX_DESCRIPTION_CHARS] + "…"

    lines = [
        "<b>Новый заказ — одобрен Gemini</b>",
        "",
        f"<b>{escape(listing.title or 'Без названия')}</b>",
        "",
        f"Бюджет: {escape(listing.budget or 'не указан')}",
        f"Осталось: {escape(listing.time_left or '—')}",
        f"Откликов: {listing.responses_count}",
        f"Заказчик: {escape(listing.author or '—')}",
        "",
        "Описание:",
        f"<pre>{escape(description)}</pre>",
        "",
        f"Gemini: <i>{escape(verdict.reason)}</i>",
        "",
        f"Ссылка: {escape(listing.url)}",
    ]
    return "\n".join(lines)


def build_offer_draft_message(listing: Listing, offer: Offer) -> str:
    """Черновик отклика (форма kwork.ru/new_offer), сгенерированный Gemini —
    все поля скопируемые, стоимость/срок не проверены против реального
    допустимого диапазона (его показывает сама страница Kwork в момент отклика)."""
    lines = [
        "<b>Черновик отклика — сгенерировано Gemini</b>",
        "",
        f"Заказ: {escape(listing.title or 'Без названия')}",
        f"Отклик: https://kwork.ru/new_offer?project={listing.id}",
        "",
        "Название заказа:",
        f"<pre>{escape(offer.title)}</pre>",
        "",
        "Описание отклика:",
        f"<pre>{escape(offer.description)}</pre>",
        "",
        f"Стоимость: <pre>{offer.cost}</pre>",
        f"Срок выполнения: <pre>{escape(offer.deadline)}</pre>",
        "",
        "⚠️ Допустимый диапазон стоимости и срока проверьте на самой странице Kwork — "
        "здесь они не сверялись с реальными ограничениями формы.",
    ]
    return "\n".join(lines)


def _split_into_chunks(text: str, max_len: int = TELEGRAM_CHUNK_CHARS) -> list[str]:
    """Режет текст по границам строк на части не длиннее `max_len` символов —
    чтобы длинный промпт не обрезался молча при упоре в лимит сообщения Telegram."""
    if len(text) <= max_len:
        return [text]

    chunks: list[str] = []
    current = ""
    for line in text.splitlines(keepends=True):
        if len(line) > max_len:
            if current:
                chunks.append(current)
                current = ""
            chunks.extend(line[i : i + max_len] for i in range(0, len(line), max_len))
            continue
        if len(current) + len(line) > max_len:
            chunks.append(current)
            current = line
        else:
            current += line
    if current:
        chunks.append(current)
    return chunks


def build_claude_prompt_messages(listing: Listing, prompt_text: str) -> list[str]:
    """Промпт для Claude Code, сгенерированный Gemini по ТЗ заказа — при необходимости
    режется на несколько сообщений (лимит Telegram — 4096 символов на сообщение),
    чтобы не обрезать рабочий текст промпта."""
    chunks = _split_into_chunks(prompt_text)
    header = f"<b>Промпт для Claude Code</b> — заказ «{escape(listing.title or 'Без названия')}»"
    total = len(chunks)
    return [
        f"{header}{f' ({i}/{total})' if total > 1 else ''}\n\n<pre>{escape(chunk)}</pre>"
        for i, chunk in enumerate(chunks, start=1)
    ]
