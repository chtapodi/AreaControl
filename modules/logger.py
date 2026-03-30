import builtins
import logging
import json
import sys
import time

class Logger:
    """Simple wrapper that uses pyscript's log when available.
    
    Supports structured logging via the `extra` keyword argument.
    When `extra` is provided, logs are formatted as JSON for parseability.
    
    Usage:
        log.info("rule_matched", extra={"rule": "motion_lights", "area": "kitchen"})
        log.info("Applying state", extra={"device": "light_kitchen", "state": {"brightness": 255}})
    """

    def __init__(self, name: str = __name__, existing=None, structured: bool = True):
        if existing is not None:
            self._logger = existing
        elif hasattr(builtins, "log"):
            self._logger = builtins.log
        else:
            self._logger = logging.getLogger(name)
        self._structured = structured
        self._name = name

    def _format_message(self, *args, extra=None):
        """Format message as JSON if structured logging is enabled."""
        # Use list comprehension instead of generator expression (pyscript ast limitation)
        parts = [str(a) for a in args]
        if extra and self._structured:
            log_entry = {
                "timestamp": time.time(),
                "message": " ".join(parts),
            }
            log_entry.update(extra)
            return json.dumps(log_entry)
        return " ".join(parts)

    def _fallback(self, level, args, exc):
        """Last-resort print to stderr when the underlying logger fails."""
        # Use list comprehension instead of generator expression (pyscript ast limitation)
        parts = [str(a) for a in args]
        msg = " ".join(parts)
        print(
            "[Logger fallback] [" + self._name + "] " + level + ": " + msg
            + " | logging error: " + str(exc),
            file=sys.stderr,
        )

    def debug(self, *args, **kwargs):
        extra = kwargs.pop("extra", None)
        try:
            msg = self._format_message(*args, extra=extra)
            self._logger.debug(msg)
        except Exception as exc:
            self._fallback("DEBUG", args, exc)

    def info(self, *args, **kwargs):
        extra = kwargs.pop("extra", None)
        try:
            msg = self._format_message(*args, extra=extra)
            self._logger.info(msg)
        except Exception as exc:
            self._fallback("INFO", args, exc)

    def warning(self, *args, **kwargs):
        extra = kwargs.pop("extra", None)
        try:
            msg = self._format_message(*args, extra=extra)
            self._logger.warning(msg)
        except Exception as exc:
            self._fallback("WARNING", args, exc)

    def error(self, *args, **kwargs):
        extra = kwargs.pop("extra", None)
        try:
            msg = self._format_message(*args, extra=extra)
            self._logger.error(msg)
        except Exception as exc:
            self._fallback("ERROR", args, exc)

    def fatal(self, *args, **kwargs):
        extra = kwargs.pop("extra", None)
        try:
            msg = self._format_message(*args, extra=extra)
            self._logger.fatal(msg)
        except Exception as exc:
            self._fallback("FATAL", args, exc)
