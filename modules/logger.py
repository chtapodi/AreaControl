"""Simple structured logging wrapper for pyscript."""

from __future__ import annotations

try:
    log  # type: ignore
except NameError:  # pragma: no cover - fallback when pyscript not present
    import logging
    log = logging.getLogger("pyscript")


LEVELS = {
    "DEBUG": 10,
    "INFO": 20,
    "WARNING": 30,
    "ERROR": 40,
}

_level = LEVELS["INFO"]


def set_level(level: str | int) -> None:
    """Set the global log level.

    ``level`` may be an integer or one of ``DEBUG``, ``INFO``,
    ``WARNING`` or ``ERROR``.
    """
    global _level
    if isinstance(level, str):
        level = level.upper()
        if level not in LEVELS:
            raise ValueError(f"Unknown log level: {level}")
        _level = LEVELS[level]
    else:
        _level = int(level)


class Logger:
    """Logger bound to a component name."""

    def __init__(self, component: str):
        self.component = component

    def _should_log(self, level: str) -> bool:
        return LEVELS[level] >= _level

    @staticmethod
    def _format(component: str, msg: str, data: dict[str, object]) -> str:
        base = f"[{component}] {msg}"
        if data:
            extras = " ".join(f"{k}={v}" for k, v in data.items())
            return f"{base} | {extras}"
        return base

    def debug(self, msg: str, **data: object) -> None:
        if self._should_log("DEBUG"):
            log.debug(self._format(self.component, msg, data))

    def info(self, msg: str, **data: object) -> None:
        if self._should_log("INFO"):
            log.info(self._format(self.component, msg, data))

    def warning(self, msg: str, **data: object) -> None:
        if self._should_log("WARNING"):
            log.warning(self._format(self.component, msg, data))

    def error(self, msg: str, **data: object) -> None:
        if self._should_log("ERROR"):
            log.error(self._format(self.component, msg, data))


def get_logger(component: str) -> Logger:
    """Return a ``Logger`` for ``component``."""
    return Logger(component)


__all__ = ["get_logger", "set_level", "Logger"]
