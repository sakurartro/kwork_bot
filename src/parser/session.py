"""
HTTP-сессия для работы с Kwork.

Устройство Kwork (выяснено эмпирически 2026-07-05):
- Раздел "Биржа проектов" (https://kwork.ru/projects) — Vue-приложение.
  Список заказов подгружается отдельным XHR: POST https://kwork.ru/projects
  с заголовком X-Requested-With: XMLHttpRequest и телом multipart/form-data
  (поле "page"). Ответ — JSON {"success": true, "data": {"pagination": {...,
  "data": [ ...заказы... ]}, ...}}. Авторизация НЕ требуется — лента заказов
  публичная.
- Сервер отвечает заголовком `Server: QRATOR` — это анти-DDoS/антибот
  Qrator Labs. При первом заходе он выставляет сессионную cookie со
  случайным именем (в наблюдении — вида "RORSSQIHEK"). Это разовая cookie
  на процесс/сессию: её нужно получить обычным GET (как это делает браузер
  при заходе на страницу) и затем переиспользовать во всех последующих
  запросах, не подменяя её и не меняя User-Agent на лету — рассинхрон
  fingerprint'а внутри одной "тёплой" сессии — типичный сигнал для антибота.
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx
from loguru import logger

from src.anti_block.delays import sleep_random
from src.anti_block.proxy import get_default_pool
from src.anti_block.user_agents import BrowserProfile, build_headers, random_profile
from src.utils.exceptions import KworkBlockedError, ParsingError

KWORK_BASE_URL = "https://kwork.ru"
PROJECTS_PATH = "/projects"
COOKIE_STORE_PATH = Path("data/kwork_cookies.json")


class KworkSession:
    """Одна "живая" HTTP-сессия с Kwork: постоянные cookies антибота,
    согласованный профиль браузера на всё время жизни сессии, аккуратный
    warm-up перед первым обращением к JSON-эндпоинту."""

    def __init__(self, profile: BrowserProfile | None = None):
        self._profile = profile or random_profile()
        self._proxy_pool = get_default_pool()
        self._client = httpx.AsyncClient(
            base_url=KWORK_BASE_URL,
            timeout=20.0,
            follow_redirects=True,
            proxy=self._proxy_pool.next(),
        )
        self._warmed_up = False
        self._load_cookies()

    def _load_cookies(self) -> None:
        if not COOKIE_STORE_PATH.exists():
            return
        try:
            data = json.loads(COOKIE_STORE_PATH.read_text(encoding="utf-8"))
            for name, value in data.items():
                self._client.cookies.set(name, value, domain="kwork.ru")
            logger.debug("Загружено {} cookie(s) из {}", len(data), COOKIE_STORE_PATH)
        except Exception:
            logger.warning("Не удалось прочитать сохранённые cookies — начинаю с чистой сессии")

    def _save_cookies(self) -> None:
        COOKIE_STORE_PATH.parent.mkdir(parents=True, exist_ok=True)
        data = {c.name: c.value for c in self._client.cookies.jar}
        COOKIE_STORE_PATH.write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    async def warm_up(self) -> None:
        """Один обычный GET /projects — как будто зашёл живой человек —
        до первого XHR-запроса за данными. Пропускается, если у нас уже
        есть сохранённые cookies от прошлого запуска."""
        if self._warmed_up or len(self._client.cookies) > 0:
            self._warmed_up = True
            return

        headers = build_headers(self._profile, xhr=False)
        resp = await self._client.get(PROJECTS_PATH, headers=headers)
        if resp.status_code != 200:
            raise KworkBlockedError(
                f"Не удалось открыть биржу заказов (status={resp.status_code})"
            )

        self._save_cookies()
        self._warmed_up = True
        await sleep_random(1.5, 3.5)  # пауза "на чтение" перед первым XHR

    async def fetch_projects_page(self, page: int = 1, category_id: int | None = None) -> dict:
        """POST /projects — вернуть сырые данные текущей страницы ленты заказов.

        `category_id` — id раздела биржи (см. src/parser/categories.py). Это то же
        самое поле `c`, которое подставляет фронтенд Kwork при переходе по
        `/projects?c=<id>`; без него отдаётся полная лента без фильтра.
        """
        await self.warm_up()

        headers = build_headers(
            self._profile, xhr=True, referer=f"{KWORK_BASE_URL}{PROJECTS_PATH}"
        )
        # files={} с (None, value) заставляет httpx собрать тело как
        # multipart/form-data — так же, как это делает FormData() в браузере.
        fields: dict[str, tuple[None, str]] = {"page": (None, str(page))}
        if category_id is not None:
            fields["c"] = (None, str(category_id))

        resp = await self._client.post(
            PROJECTS_PATH,
            headers=headers,
            files=fields,
        )

        content_type = resp.headers.get("content-type", "")
        if resp.status_code != 200 or "json" not in content_type:
            raise KworkBlockedError(
                f"Похоже на антибот-защиту вместо данных "
                f"(status={resp.status_code}, content-type={content_type!r})"
            )

        payload = resp.json()
        if not payload.get("success"):
            raise ParsingError("Kwork ответил success=false")

        self._save_cookies()
        return payload["data"]

    async def aclose(self) -> None:
        await self._client.aclose()
