import builtins
import logging
import json
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

    def _format_message(self, *args, extra=None):
        """Format message as JSON if structured logging is enabled."""
        if extra and self._structured:
            log_entry = {
                "timestamp": time.time(),
                "message": " ".join(str(a) for a in args),
            }
            log_entry.update(extra)
            return json.dumps(log_entry)
        return " ".join(str(a) for a in args)

    def info(self, *args, **kwargs):
        extra = kwargs.pop("extra", None)
        try:
            msg = self._format_message(*args, extra=extra)
            self._logger.info(msg)
        except Exception:
            pass

    def warning(self, *args, **kwargs):
        extra = kwargs.pop("extra", None)
        try:
            msg = self._format_message(*args, extra=extra)
            self._logger.warning(msg)
        except Exception:
            pass

    def fatal(self, *args, **kwargs):
        extra = kwargs.pop("extra", None)
        try:
            msg = self._format_message(*args, extra=extra)
            self._logger.fatal(msg)
        except Exception:
            pass
