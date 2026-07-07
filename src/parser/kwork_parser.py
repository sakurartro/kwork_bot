"""
Сбор новых заказов с биржи Kwork поверх KworkSession.
"""

from __future__ import annotations

from loguru import logger

from src.anti_block.delays import backoff_sleep, sleep_random
from src.parser.models import Listing
from src.parser.session import KworkSession
from src.utils.exceptions import KworkBlockedError, ParsingError

MAX_ATTEMPTS = 3


async def _fetch_page_with_backoff(
    session: KworkSession, page: int, category_id: int | None = None
) -> dict:
    last_error: Exception | None = None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            return await session.fetch_projects_page(page, category_id=category_id)
        except (KworkBlockedError, ParsingError) as exc:
            last_error = exc
            logger.warning(
                "Попытка {}/{} для страницы {} не удалась: {}",
                attempt,
                MAX_ATTEMPTS,
                page,
                exc,
            )
            if attempt < MAX_ATTEMPTS:
                await backoff_sleep(attempt)

    assert last_error is not None
    raise last_error


async def fetch_new_listings(
    session: KworkSession,
    pages: int = 1,
    delay_between_pages: tuple[float, float] = (2.0, 5.0),
    category_id: int | None = None,
) -> tuple[list[Listing], int]:
    """Забрать первые `pages` страниц ленты заказов (самые новые первыми).

    `category_id` — необязательный фильтр по разделу биржи (src/parser/categories.py);
    без него отдаётся полная лента без фильтра.
    Возвращает (список объявлений, общее число заказов на бирже сейчас).
    Между запросами разных страниц выдерживается случайная пауза — чтобы
    даже "разовый" сбор нескольких страниц не выглядел как залповый обстрел.
    """
    all_listings: list[Listing] = []
    total_on_site = 0

    for page in range(1, pages + 1):
        data = await _fetch_page_with_backoff(session, page, category_id=category_id)
        pagination = data["pagination"]
        total_on_site = pagination.get("total", total_on_site)
        items = pagination.get("data", [])
        all_listings.extend(Listing.from_api(item) for item in items)

        if page < pages:
            await sleep_random(*delay_between_pages)

    logger.info("Собрано {} объявлений (страниц: {})", len(all_listings), pages)
    return all_listings, total_on_site
