from __future__ import annotations

import logging

DEFAULT_LOG_LEVEL = "INFO"


def configure_logging() -> None:
    logging.basicConfig(
        level=DEFAULT_LOG_LEVEL,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
