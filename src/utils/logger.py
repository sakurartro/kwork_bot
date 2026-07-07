"""
Настройка логирования (loguru): консоль + ротация файлов в logs/.
"""

from __future__ import annotations

import sys
from pathlib import Path

from loguru import logger

_configured = False


def setup_logging(level: str = "INFO", log_dir: str = "logs") -> None:
    global _configured
    if _configured:
        return

    Path(log_dir).mkdir(parents=True, exist_ok=True)

    logger.remove()
    logger.add(
        sys.stderr,
        level=level,
        colorize=True,
        format=(
            "<green>{time:HH:mm:ss}</green> | <level>{level:<8}</level> | "
            "<cyan>{name}</cyan> - <level>{message}</level>"
        ),
    )
    logger.add(
        f"{log_dir}/app.log",
        level=level,
        rotation="5 MB",
        retention=5,
        encoding="utf-8",
    )

    _configured = True
