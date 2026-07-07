"""
Управление пулом прокси (опционально, если задан PROXY_LIST в .env).
"""

from __future__ import annotations

import itertools

from config.settings import get_settings


class ProxyPool:
    def __init__(self, proxies: list[str] | None = None):
        proxies = proxies or []
        self._cycle = itertools.cycle(proxies) if proxies else None

    @property
    def has_proxies(self) -> bool:
        return self._cycle is not None

    def next(self) -> str | None:
        """Отдать следующий прокси по кругу, либо None если пул пуст (прямое подключение)."""
        return next(self._cycle) if self._cycle else None


def get_default_pool() -> ProxyPool:
    settings = get_settings()
    raw = settings.proxy_list or ""
    proxies = [p.strip() for p in raw.split(",") if p.strip()]
    return ProxyPool(proxies)
