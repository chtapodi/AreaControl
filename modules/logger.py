import builtins
import logging


class _ColoredFormatter(logging.Formatter):
    COLORS = {
        logging.DEBUG: "\033[36m",
        logging.INFO: "\033[32m",
        logging.WARNING: "\033[33m",
        logging.ERROR: "\033[31m",
        logging.CRITICAL: "\033[35m",
    }

    def format(self, record):
        levelno = record.levelno
        color = self.COLORS.get(levelno, "")
        reset = "\033[0m" if color else ""
        record.levelname = f"{color}{record.levelname}{reset}"
        return super().format(record)

class Logger:
    """Wrapper around pyscript or standard logging with sensible defaults."""

    def __init__(self, name: str = __name__, existing=None, *, level=logging.INFO):
        if existing is not None:
            self._logger = existing
            self._external = True
        elif hasattr(builtins, "log"):
            self._logger = builtins.log
            self._external = True
        else:
            logger = logging.getLogger(name)
            if not logger.handlers:
                handler = logging.StreamHandler()
                fmt = "[%(levelname)s] %(asctime)s - %(name)s: %(message)s"
                handler.setFormatter(_ColoredFormatter(fmt))
                logger.addHandler(handler)
            logger.setLevel(level)
            self._logger = logger
            self._external = False

    def _call(self, name: str, *args, **kwargs):
        try:
            fn = getattr(self._logger, name)
        except AttributeError:
            return
        try:
            fn(*args, **kwargs)
        except Exception:
            pass

    def set_level(self, level: int) -> None:
        if not self._external and hasattr(self._logger, "setLevel"):
            self._logger.setLevel(level)

    def debug(self, *args, **kwargs):
        self._call("debug", *args, **kwargs)

    def info(self, *args, **kwargs):
        self._call("info", *args, **kwargs)

    def warning(self, *args, **kwargs):
        self._call("warning", *args, **kwargs)

    def error(self, *args, **kwargs):
        self._call("error", *args, **kwargs)

    def fatal(self, *args, **kwargs):
        # Some loggers use "critical" instead of "fatal" so try both
        if hasattr(self._logger, "fatal"):
            self._call("fatal", *args, **kwargs)
        else:
            self._call("critical", *args, **kwargs)

    critical = fatal
