class Logger:
    """Thin wrapper around the builtin pyscript `log` object."""
    def __init__(self, log_obj):
        self.log = log_obj

    def _fmt(self, msg, **kwargs):
        if kwargs:
            parts = [msg] + [f"{k}={v!r}" for k, v in kwargs.items()]
            return " ".join(parts)
        return msg

    def info(self, msg, **kwargs):
        if hasattr(self.log, "info"):
            self.log.info(self._fmt(msg, **kwargs))

    def warning(self, msg, **kwargs):
        if hasattr(self.log, "warning"):
            self.log.warning(self._fmt(msg, **kwargs))

    def debug(self, msg, **kwargs):
        if hasattr(self.log, "debug"):
            self.log.debug(self._fmt(msg, **kwargs))
        else:
            if hasattr(self.log, "info"):
                self.log.info(self._fmt(msg, **kwargs))
