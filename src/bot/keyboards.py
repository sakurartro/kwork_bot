"""Клавиатуры и инлайн-кнопки."""

from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

REPLY_CALLBACK_PREFIX = "reply:"
OFFER_CALLBACK_PREFIX = "offer:"
CLAUDE_PROMPT_CALLBACK_PREFIX = "claudeprompt:"


def build_order_keyboard(listing_id: int) -> InlineKeyboardMarkup:
    """Кнопки под карточкой нового заказа:
    - «Ответить заказчику» — живой ответ на вставленное сообщение (handlers.cb_reply);
    - «Создать запрос» — черновик отклика (форма kwork.ru/new_offer) (handlers.cb_offer);
    - «Промпт для Claude Code» — детальный промпт по ТЗ заказа (handlers.cb_claude_prompt)."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="💬 Ответить заказчику",
                    callback_data=f"{REPLY_CALLBACK_PREFIX}{listing_id}",
                )
            ],
            [
                InlineKeyboardButton(
                    text="📝 Создать запрос",
                    callback_data=f"{OFFER_CALLBACK_PREFIX}{listing_id}",
                )
            ],
            [
                InlineKeyboardButton(
                    text="🤖 Промпт для Claude Code",
                    callback_data=f"{CLAUDE_PROMPT_CALLBACK_PREFIX}{listing_id}",
                )
            ],
        ]
    )
