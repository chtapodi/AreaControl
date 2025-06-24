import builtins
import logging

class Logger:
    """Simple wrapper that uses pyscript's log when available."""

    def __init__(self, name: str = __name__, existing=None):
        if existing is not None:
            self._logger = existing
        elif hasattr(builtins, "log"):
            self._logger = builtins.log
        else:
            self._logger = logging.getLogger(name)

    def info(self, *args, **kwargs):
        try:
            self._logger.info(*args, **kwargs)
        except Exception:
            pass

    def warning(self, *args, **kwargs):
        try:
            self._logger.warning(*args, **kwargs)
        except Exception:
            pass

    def fatal(self, *args, **kwargs):
        try:
            self._logger.fatal(*args, **kwargs)
        except Exception:
            pass
