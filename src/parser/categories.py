"""Разделы (категории верхнего уровня) биржи заказов Kwork.

Kwork не отдаёт список категорий через тот же JSON API, что и сами заказы —
он встроен прямо в HTML страницы https://kwork.ru/projects как
`window.stateData.categoriesWithFavoritesList`. Список ниже снят оттуда
эмпирически (2026-07-05) и захардкожен, так как раздела биржи меняются
исключительно редко.

Проверено вживую: `POST /projects` с полем `c=<id>` (id раздела, тот же, что
`CATID` в этом словаре) возвращает только заказы, чей `category_id`
относится к подкатегориям этого раздела — см. src/parser/session.py.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Category:
    id: int
    name: str


CATEGORIES: list[Category] = [
    Category(15, "Дизайн"),
    Category(11, "Разработка и IT"),
    Category(5, "Тексты и переводы"),
    Category(17, "SEO и трафик"),
    Category(45, "Соцсети и маркетинг"),
    Category(7, "Аудио, видео, съемка"),
    Category(83, "Бизнес и жизнь"),
]
