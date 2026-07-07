"""Обёртка над Gemini API (унифицированный SDK `google-genai`) для классификации заказов Kwork."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

from google import genai
from google.genai import types
from loguru import logger
from pydantic import BaseModel, Field

from src.ai.prompts import (
    PROMPT_CLASSIFY_SYSTEM,
    PROMPT_CLASSIFY_USER_TEMPLATE,
    PROMPT_CLAUDE_SYSTEM,
    PROMPT_CLAUDE_USER_TEMPLATE,
    PROMPT_OFFER_SYSTEM,
    PROMPT_OFFER_USER_TEMPLATE,
    PROMPT_REPLY_SYSTEM,
    PROMPT_REPLY_USER_TEMPLATE,
)
from src.anti_block.delays import backoff_sleep
from src.utils.exceptions import GeminiError

MAX_ATTEMPTS = 5
MAX_RETRY_DELAY_S = 40.0
MAX_OFFER_DESCRIPTION_CHARS = 2000  # лимит поля "Описание" в форме отклика Kwork
MIN_OFFER_COST_RUB = 2000  # минимально допустимая стоимость заказа на Kwork (site-wide)


def _quota_retry_delay_s(exc: Exception) -> float | None:
    """Достать точную рекомендованную задержку из ответа Gemini на 429
    (`google.rpc.RetryInfo.retryDelay`, напр. "22s") — вместо того, чтобы
    угадывать паузу самим, раз сервер прямо говорит, сколько ждать."""
    details = getattr(exc, "details", None)
    if not isinstance(details, dict):
        return None
    for item in details.get("error", {}).get("details", []):
        if not item.get("@type", "").endswith("RetryInfo"):
            continue
        raw = item.get("retryDelay", "")
        if raw.endswith("s"):
            try:
                return min(float(raw[:-1]), MAX_RETRY_DELAY_S)
            except ValueError:
                return None
    return None


class ClassificationVerdict(BaseModel):
    """Строгая форма ответа Gemini (`response_schema`) — модель обязана вернуть
    именно эти поля, свободный текст парсить не нужно."""

    can_be_done_by_ai: bool = Field(
        description="True только если Claude Code может выполнить заказ ПОЛНОСТЬЮ самостоятельно"
    )
    reason: str = Field(description="Короткое обоснование вердикта на русском, 1-2 предложения")


@dataclass(frozen=True, slots=True)
class Classification:
    can_be_done_by_ai: bool
    reason: str


class OfferDraft(BaseModel):
    """Строгая форма черновика отклика (`response_schema`) — поля один в один
    соответствуют форме kwork.ru/new_offer («Предложить услугу»)."""

    title: str = Field(
        description="Название кворка/предложения под этот заказ, не длиннее 70 символов, без кавычек"
    )
    description: str = Field(
        description="Текст отклика — как именно будет выполнена работа, 150-2000 символов, живым языком"
    )
    cost: int = Field(description="Предлагаемая стоимость в рублях (целое число)")
    deadline: str = Field(description="Короткая рекомендация по сроку выполнения, напр. '3 дня'")


@dataclass(frozen=True, slots=True)
class Offer:
    title: str
    description: str
    cost: int
    deadline: str


class GeminiClient:
    """Классификация заказов: может ли Claude Code выполнить их полностью самостоятельно."""

    def __init__(self, api_key: str, model: str) -> None:
        self._client = genai.Client(api_key=api_key)
        self._model = model

    async def _generate_with_retry(
        self,
        *,
        action: str,
        prompt: str,
        config: types.GenerateContentConfig,
    ) -> types.GenerateContentResponse:
        """Общий цикл ретраев (уважает `RetryInfo.retryDelay` от 429, до
        `MAX_ATTEMPTS` попыток) — переиспользуется классификацией и генерацией
        живого ответа заказчику, чтобы не дублировать логику квот/бэкоффа."""
        last_error: Exception | None = None
        for attempt in range(1, MAX_ATTEMPTS + 1):
            try:
                return await self._client.aio.models.generate_content(
                    model=self._model,
                    contents=prompt,
                    config=config,
                )
            except Exception as exc:  # noqa: BLE001 — любая ошибка API/сети/парсинга уходит в ретрай
                last_error = exc
                logger.warning("Gemini {} попытка {}/{} не удалась: {}", action, attempt, MAX_ATTEMPTS, exc)
                if attempt < MAX_ATTEMPTS:
                    quota_delay = _quota_retry_delay_s(exc)
                    if quota_delay is not None:
                        await asyncio.sleep(quota_delay)
                    else:
                        await backoff_sleep(attempt, base=3.0)

        assert last_error is not None
        raise GeminiError(f"Не удалось выполнить запрос к Gemini ({action}): {last_error}") from last_error

    async def classify(self, title: str, description: str) -> Classification:
        """Строго структурированный вердикт по одному заказу — без свободного текста,
        Gemini обязана вернуть JSON по `ClassificationVerdict` (`response_schema`)."""
        prompt = PROMPT_CLASSIFY_USER_TEMPLATE.format(
            title=title or "(без названия)",
            description=description or "(без описания)",
        )
        response = await self._generate_with_retry(
            action="classify",
            prompt=prompt,
            config=types.GenerateContentConfig(
                system_instruction=PROMPT_CLASSIFY_SYSTEM,
                response_mime_type="application/json",
                response_schema=ClassificationVerdict,
                temperature=0.0,
            ),
        )
        verdict = response.parsed
        if not isinstance(verdict, ClassificationVerdict):
            raise GeminiError(f"Gemini вернула ответ без структурированных данных: {response.text!r}")
        return Classification(can_be_done_by_ai=verdict.can_be_done_by_ai, reason=verdict.reason)

    async def generate_human_reply(self, title: str, description: str, client_message: str) -> str:
        """Живой, «человечный» ответ заказчику на его сообщение в контексте
        конкретного заказа (заголовок + описание ТЗ)."""
        prompt = PROMPT_REPLY_USER_TEMPLATE.format(
            title=title or "(без названия)",
            description=description or "(без описания)",
            client_message=client_message,
        )
        response = await self._generate_with_retry(
            action="generate_human_reply",
            prompt=prompt,
            config=types.GenerateContentConfig(
                system_instruction=PROMPT_REPLY_SYSTEM,
                temperature=0.7,
            ),
        )
        reply = (response.text or "").strip()
        if not reply:
            raise GeminiError("Gemini вернула пустой ответ")
        return reply

    async def generate_offer(self, title: str, description: str, budget: str | None) -> Offer:
        """Черновик отклика на заказ (форма «Предложить услугу» на Kwork):
        название кворка, текст отклика, стоимость, срок выполнения. Реальный
        допустимый диапазон стоимости показывает сама страница Kwork в момент
        отклика — здесь он не проверяется, только предлагается разумное значение."""
        prompt = PROMPT_OFFER_USER_TEMPLATE.format(
            title=title or "(без названия)",
            description=description or "(без описания)",
            budget=budget or "не указан",
        )
        response = await self._generate_with_retry(
            action="generate_offer",
            prompt=prompt,
            config=types.GenerateContentConfig(
                system_instruction=PROMPT_OFFER_SYSTEM,
                response_mime_type="application/json",
                response_schema=OfferDraft,
                temperature=0.6,
            ),
        )
        draft = response.parsed
        if not isinstance(draft, OfferDraft):
            raise GeminiError(f"Gemini вернула отклик без структурированных данных: {response.text!r}")

        return Offer(
            title=draft.title.strip()[:70],
            description=draft.description.strip()[:MAX_OFFER_DESCRIPTION_CHARS],
            cost=max(draft.cost, MIN_OFFER_COST_RUB),
            deadline=draft.deadline.strip(),
        )

    async def generate_claude_prompt(self, title: str, description: str) -> str:
        """Максимально подробный и точный промпт для Claude Code по ТЗ заказчика —
        низкая temperature: тут важна точность и полнота, а не «живость» текста."""
        prompt = PROMPT_CLAUDE_USER_TEMPLATE.format(
            title=title or "(без названия)",
            description=description or "(без описания)",
        )
        response = await self._generate_with_retry(
            action="generate_claude_prompt",
            prompt=prompt,
            config=types.GenerateContentConfig(
                system_instruction=PROMPT_CLAUDE_SYSTEM,
                temperature=0.2,
            ),
        )
        text = (response.text or "").strip()
        if not text:
            raise GeminiError("Gemini вернула пустой промпт")
        return text

    async def aclose(self) -> None:
        self._client.close()
