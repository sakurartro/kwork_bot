"""
Кастомные исключения проекта.
"""


class KworkError(Exception):
    """Базовая ошибка при работе с Kwork."""


class KworkAuthError(KworkError):
    """Не удалось авторизоваться / сессия недействительна."""


class KworkBlockedError(KworkError):
    """Похоже на антибот-защиту (Qrator) или блокировку вместо ожидаемого ответа."""


class ParsingError(KworkError):
    """Ответ получен, но не удалось извлечь из него данные (неожиданный формат)."""


class GeminiError(Exception):
    """Ошибка при обращении к Gemini API."""
