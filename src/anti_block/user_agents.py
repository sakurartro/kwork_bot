"""
Пул реалистичных браузерных профилей (User-Agent + согласованные заголовки).

Важно: профиль выбирается ОДИН раз на сессию и не меняется до её конца.
Смена User-Agent посреди уже "тёплой" сессии (с живыми cookies антибота)
сама по себе выглядит подозрительно — реальный браузер не мутирует свой
fingerprint между запросами.
"""

from __future__ import annotations

import random
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class BrowserProfile:
    user_agent: str
    accept_language: str
    sec_ch_ua: str = ""
    sec_ch_ua_platform: str = ""


_PROFILES: list[BrowserProfile] = [
    BrowserProfile(
        user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        ),
        accept_language="ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
        sec_ch_ua='"Chromium";v="124", "Google Chrome";v="124", "Not-A.Brand";v="99"',
        sec_ch_ua_platform='"Windows"',
    ),
    BrowserProfile(
        user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36 Edg/125.0.0.0"
        ),
        accept_language="ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
        sec_ch_ua='"Microsoft Edge";v="125", "Chromium";v="125", "Not-A.Brand";v="99"',
        sec_ch_ua_platform='"Windows"',
    ),
    BrowserProfile(
        user_agent=(
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 "
            "(KHTML, like Gecko) Version/17.4 Safari/605.1.15"
        ),
        accept_language="ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
    ),
    BrowserProfile(
        user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:126.0) "
            "Gecko/20100101 Firefox/126.0"
        ),
        accept_language="ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
    ),
    BrowserProfile(
        user_agent=(
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        ),
        accept_language="ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
        sec_ch_ua='"Chromium";v="124", "Google Chrome";v="124", "Not-A.Brand";v="99"',
        sec_ch_ua_platform='"macOS"',
    ),
]


def random_profile() -> BrowserProfile:
    """Выбрать случайный профиль браузера — вызывать один раз при создании сессии."""
    return random.choice(_PROFILES)


def build_headers(profile: BrowserProfile, *, xhr: bool = False, referer: str | None = None) -> dict[str, str]:
    """Собрать согласованный набор заголовков под выбранный профиль.

    xhr=True имитирует fetch/axios-запрос со страницы (как это делает сам
    фронтенд Kwork при подгрузке ленты заказов), xhr=False — обычную
    навигацию браузера (первый заход на страницу).
    """
    headers: dict[str, str] = {
        "User-Agent": profile.user_agent,
        "Accept-Language": profile.accept_language,
    }

    if profile.sec_ch_ua:
        headers["Sec-Ch-Ua"] = profile.sec_ch_ua
        headers["Sec-Ch-Ua-Platform"] = profile.sec_ch_ua_platform
        headers["Sec-Ch-Ua-Mobile"] = "?0"

    if xhr:
        headers["X-Requested-With"] = "XMLHttpRequest"
        headers["Accept"] = "application/json, text/plain, */*"
    else:
        headers["Accept"] = (
            "text/html,application/xhtml+xml,application/xml;q=0.9,"
            "image/avif,image/webp,*/*;q=0.8"
        )

    if referer:
        headers["Referer"] = referer

    return headers
