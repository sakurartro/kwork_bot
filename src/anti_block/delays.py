"""
Рандомные задержки против блокировок.
"""

from __future__ import annotations

import asyncio
import random


async def sleep_random(min_s: float, max_s: float) -> float:
    """Асинхронная пауза случайной длины из диапазона [min_s, max_s]. Возвращает фактическую длительность (для логов/UI)."""
    duration = random.uniform(min_s, max_s)
    await asyncio.sleep(duration)
    return duration


async def backoff_sleep(attempt: int, base: float = 3.0, max_s: float = 60.0) -> float:
    """Экспоненциальный backoff с джиттером для повторных попыток после ошибки/бана."""
    duration = min(max_s, base * (2 ** (attempt - 1)))
    duration += random.uniform(0, base)
    await asyncio.sleep(duration)
    return duration
