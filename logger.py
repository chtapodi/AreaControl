import logging
from typing import Any

class Logger:
    """Lightweight wrapper around :mod:`logging` used across the project."""

    def __init__(self, name: str = __name__):
        self._log = logging.getLogger(name)

    def info(self, *args: Any, **kwargs: Any) -> None:
        self._log.info(*args, **kwargs)

    def warning(self, *args: Any, **kwargs: Any) -> None:
        self._log.warning(*args, **kwargs)

    def fatal(self, *args: Any, **kwargs: Any) -> None:
        self._log.fatal(*args, **kwargs)

    def debug(self, *args: Any, **kwargs: Any) -> None:
        self._log.debug(*args, **kwargs)

def get_logger(name: str | None = None) -> Logger:
    return Logger(name if name else __name__)
