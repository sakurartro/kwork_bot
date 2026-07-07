"""
Локальный веб-сервер для тестирования парсера Kwork (без Telegram).

Запуск: python run_web.py   →  http://127.0.0.1:8000

Логика анти-блокировки перенесена и на сам локальный API: повторный реальный
поход на Kwork разрешён не чаще, чем раз в случайный интервал 90–150 секунд
(PARSE_DELAY_MIN/MAX). Пока идёт "остывание", эндпоинт просто отдаёт
последний закэшированный результат — сайт не спамит биржу, даже если
пользователь долбит кнопку "Обновить".
"""

from __future__ import annotations

import random
import time
from collections import defaultdict
from contextlib import asynccontextmanager
from dataclasses import asdict
from pathlib import Path

from fastapi import FastAPI, Query
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from loguru import logger

from config.settings import get_settings
from src.ai.gemini_client import Classification, GeminiClient
from src.parser.categories import CATEGORIES
from src.parser.kwork_parser import fetch_new_listings
from src.parser.models import Listing
from src.parser.session import KworkSession
from src.utils.exceptions import GeminiError, KworkError
from src.utils.logger import setup_logging

STATIC_DIR = Path(__file__).parent / "static"


class CategoryState:
    """Кэш и антиспам-охлаждение для одной ленты (весь сайт или один раздел).

    Разделы независимы: переключение на ещё не запрошенный раздел не должно
    ждать охлаждения от предыдущего — это не повторный клик по той же кнопке,
    а осознанно новый запрос пользователя."""

    def __init__(self) -> None:
        self.cache: list[dict] = []
        self.seen_ids: set[int] = set()
        self.last_fetch_at: float = 0.0
        self.cooldown_s: float = 0.0
        self.total_on_site: int = 0
        self.checked_count: int = 0


class AppState:
    def __init__(self) -> None:
        self.session: KworkSession | None = None
        self.gemini: GeminiClient | None = None
        self.by_category: dict[str, CategoryState] = defaultdict(CategoryState)
        # Вердикт Gemini по заказу не зависит от раздела, в котором мы его увидели —
        # кэшируем по id заказа один раз, чтобы не тратить квоту на заказы,
        # которые остаются в топе ленты между обновлениями.
        self.classifications: dict[int, Classification] = {}


state = AppState()


async def _classify_new_listings(listings: list[Listing]) -> None:
    """Дозаполнить state.classifications вердиктами для заказов, которых там ещё нет.

    Строго последовательно: у бесплатной квоты Gemini на модель — считанные
    запросы в минуту, параллельный залп по всем новым заказам сразу же
    выжигает лимит и валит все запросы в 429 (см. ретраи в GeminiClient —
    они сами honour'ят RetryInfo.retryDelay от API)."""
    assert state.gemini is not None
    to_classify = [listing for listing in listings if listing.id not in state.classifications]

    for listing in to_classify:
        try:
            state.classifications[listing.id] = await state.gemini.classify(
                listing.title, listing.description
            )
        except GeminiError as exc:
            logger.warning("Gemini не смогла классифицировать заказ {}: {}", listing.id, exc)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    setup_logging(settings.log_level)
    state.session = KworkSession()

    if settings.gemini_api_key:
        state.gemini = GeminiClient(api_key=settings.gemini_api_key, model=settings.gemini_model)
        logger.info("Gemini-клиент создан (модель {})", settings.gemini_model)
    else:
        logger.warning(
            "GEMINI_API_KEY не задан в .env — заказы не будут проверяться и не будут показаны на сайте"
        )

    logger.info("Kwork-сессия создана, локальный сервер парсера запущен на http://{}:{}", settings.web_host, settings.web_port)
    try:
        yield
    finally:
        if state.session:
            await state.session.aclose()
        if state.gemini:
            await state.gemini.aclose()


app = FastAPI(title="Kwork Parser — локальный тест", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/categories")
async def api_categories() -> JSONResponse:
    return JSONResponse([{"id": c.id, "name": c.name} for c in CATEGORIES])


@app.get("/api/listings")
async def api_listings(
    pages: int = Query(1, ge=1, le=3),
    category: int | None = Query(None),
) -> JSONResponse:
    settings = get_settings()
    cat_state = state.by_category[str(category) if category is not None else "all"]

    if state.gemini is None:
        return JSONResponse(
            {
                "status": "error",
                "message": (
                    "GEMINI_API_KEY не задан в .env — без него заказы не проверяются и не "
                    "показываются. Получите ключ на https://aistudio.google.com/apikey, "
                    "впишите в .env и перезапустите сервер."
                ),
                "listings": cat_state.cache,
                "total_on_site": cat_state.total_on_site,
            },
            status_code=503,
        )

    now = time.monotonic()
    elapsed = (now - cat_state.last_fetch_at) if cat_state.last_fetch_at else None

    if elapsed is not None and elapsed < cat_state.cooldown_s:
        remaining = round(cat_state.cooldown_s - elapsed, 1)
        return JSONResponse(
            {
                "status": "cooldown",
                "retry_after": remaining,
                "listings": cat_state.cache,
                "total_on_site": cat_state.total_on_site,
                "checked_count": cat_state.checked_count,
            }
        )

    try:
        assert state.session is not None
        listings, total = await fetch_new_listings(state.session, pages=pages, category_id=category)
    except KworkError as exc:
        logger.exception("Ошибка парсинга Kwork")
        return JSONResponse(
            {
                "status": "error",
                "message": str(exc),
                "listings": cat_state.cache,
                "total_on_site": cat_state.total_on_site,
            },
            status_code=502,
        )

    await _classify_new_listings(listings)

    approved = [
        listing
        for listing in listings
        if (verdict := state.classifications.get(listing.id)) is not None and verdict.can_be_done_by_ai
    ]

    new_ids = {listing.id for listing in approved} - cat_state.seen_ids
    cat_state.seen_ids |= new_ids
    cat_state.cache = [
        {
            **asdict(listing),
            "is_new": listing.id in new_ids,
            "ai_reason": state.classifications[listing.id].reason,
        }
        for listing in approved
    ]
    cat_state.total_on_site = total
    cat_state.checked_count = len(listings)
    cat_state.last_fetch_at = now
    cat_state.cooldown_s = random.uniform(settings.parse_delay_min, settings.parse_delay_max)

    return JSONResponse(
        {
            "status": "ok",
            "listings": cat_state.cache,
            "retry_after": cat_state.cooldown_s,
            "total_on_site": cat_state.total_on_site,
            "checked_count": cat_state.checked_count,
        }
    )
