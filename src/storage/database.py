"""Хранилище (SQLite через aiosqlite) — персистентная дедупликация заказов
между перезапусками бота (в отличие от in-memory `seen_ids` в src/web/app.py,
который переживает только один процесс локального тестового сервера)."""

from __future__ import annotations

from pathlib import Path

import aiosqlite

from src.storage.models import SCHEMA_SQL


class Database:
    def __init__(self, path: str) -> None:
        self._path = path
        self._conn: aiosqlite.Connection | None = None

    async def connect(self) -> None:
        Path(self._path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = await aiosqlite.connect(self._path)
        await self._conn.execute(SCHEMA_SQL)
        await self._conn.commit()

    async def is_seen(self, listing_id: int) -> bool:
        assert self._conn is not None
        cursor = await self._conn.execute(
            "SELECT 1 FROM seen_listings WHERE listing_id = ?", (listing_id,)
        )
        row = await cursor.fetchone()
        return row is not None

    async def mark_seen(self, listing_id: int, title: str, url: str, status: str) -> None:
        assert self._conn is not None
        await self._conn.execute(
            "INSERT OR REPLACE INTO seen_listings (listing_id, title, url, status) VALUES (?, ?, ?, ?)",
            (listing_id, title, url, status),
        )
        await self._conn.commit()

    async def close(self) -> None:
        if self._conn is not None:
            await self._conn.close()
