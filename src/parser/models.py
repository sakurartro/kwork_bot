"""
Модели данных парсера.
"""

from __future__ import annotations

import html
from dataclasses import dataclass


def format_budget(price_limit: object) -> str | None:
    """'3000.00' -> '3 000 ₽'. Возвращает None, если бюджет не указан/нулевой."""
    if price_limit in (None, ""):
        return None
    try:
        value = float(price_limit)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return str(price_limit)
    if value <= 0:
        return None
    if value == int(value):
        return f"{int(value):,} ₽".replace(",", " ")
    return f"{value:,.2f} ₽".replace(",", " ")


@dataclass(frozen=True, slots=True)
class Listing:
    """Нормализованное объявление с биржи Kwork (один заказ)."""

    id: int
    title: str
    description: str
    url: str
    budget: str | None
    responses_count: int
    posted_at: str | None
    time_left: str | None
    author: str | None

    @classmethod
    def from_api(cls, raw: dict) -> "Listing":
        """Собрать Listing из сырого JSON-объекта 'want', который отдаёт
        POST https://kwork.ru/projects (см. src/parser/session.py)."""
        want_id = int(raw["id"])
        user = raw.get("user") or {}
        # Kwork отдаёт name/description с неразэкранированными HTML-сущностями
        # (&ldquo;, &rsquo; и т.п.) — их фронтенд Vue декодирует через v-html,
        # а нам нужно сделать это самим, раз мы отдаём обычный текст.
        return cls(
            id=want_id,
            title=html.unescape(raw.get("name") or "").strip(),
            description=html.unescape(raw.get("description") or "").strip(),
            url=f"https://kwork.ru/projects/{want_id}/view",
            budget=format_budget(raw.get("priceLimit")),
            responses_count=int(raw.get("kwork_count") or 0),
            posted_at=raw.get("date_create"),
            time_left=raw.get("timeLeft"),
            author=user.get("username"),
        )
