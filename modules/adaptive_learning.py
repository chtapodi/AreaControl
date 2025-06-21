import time
from collections import Counter

try:
    from pyscript import service
except Exception:
    def service(func=None, **kwargs):
        if func is not None:
            return func
        def wrapper(f):
            return f
        return wrapper

_learner_instance = None

class AdaptiveLearner:
    """Simple learner that records presence and rule events."""

    def __init__(self, max_events: int = 1000):
        self.max_events = max_events
        self.presence_events = []  # list of (timestamp, area)
        self.rule_events = []      # list of (timestamp, rule_name)

    def record_presence(self, area: str, timestamp: float | None = None) -> None:
        if timestamp is None:
            timestamp = time.time()
        self.presence_events.append((timestamp, area))
        if len(self.presence_events) > self.max_events:
            self.presence_events.pop(0)

    def record_rule_event(self, rule_name: str, timestamp: float | None = None) -> None:
        if timestamp is None:
            timestamp = time.time()
        self.rule_events.append((timestamp, rule_name))
        if len(self.rule_events) > self.max_events:
            self.rule_events.pop(0)

    def get_presence_log(self):
        return list(self.presence_events)

    def get_rule_log(self):
        return list(self.rule_events)

    def _sequence_counts(self, n: int = 2) -> Counter:
        events = [area for _ts, area in self.presence_events]
        counts = Counter()
        for i in range(len(events) - n + 1):
            seq = tuple(events[i:i + n])
            counts[seq] += 1
        return counts

    def suggest_rules(self, *, n: int = 2, top: int = 3):
        """Return most common presence sequences."""
        counts = self._sequence_counts(n)
        common = counts.most_common(top)
        return [{"sequence": list(seq), "count": cnt} for seq, cnt in common]


def get_learner() -> AdaptiveLearner:
    global _learner_instance
    if _learner_instance is None:
        _learner_instance = AdaptiveLearner()
    return _learner_instance


@service
def suggest_rules(top: int = 3):
    """Service wrapper to return suggested rules."""
    learner = get_learner()
    return learner.suggest_rules(top=top)
