"""Adaptive learning utilities for AreaControl."""

import os
import time
from datetime import datetime
from collections import defaultdict
import yaml

try:
    service
except NameError:
    def service(func):
        return func

try:
    log
except NameError:
    import logging
    log = logging.getLogger(__name__)


class AdaptiveLearner:
    """Log events and analyze common patterns."""

    def __init__(self, history_file: str = "learning_history.yml"):
        self.history_file = history_file
        self.history = []
        self._load()

    def _load(self):
        if os.path.exists(self.history_file):
            with open(self.history_file, "r") as f:
                self.history = yaml.safe_load(f) or []
        else:
            self.history = []

    def _save(self):
        with open(self.history_file, "w") as f:
            yaml.safe_dump(self.history, f)

    def collect_event(self, event: dict) -> None:
        """Record a fired rule or presence event."""
        ts = event.get("timestamp", time.time())
        entry = {
            "timestamp": float(ts),
            "event_type": event.get("event_type", "rule"),
            "device": event.get("device_name"),
            "rule": event.get("rule_name"),
            "area": event.get("area"),
            "state": event.get("final_state"),
        }
        self.history.append(entry)
        self._save()

    def record_presence(self, area: str, timestamp: float | None = None) -> None:
        self.collect_event({"event_type": "presence", "area": area, "timestamp": timestamp})

    def analyze_patterns(self) -> dict:
        """Return aggregated stats from the history."""
        brightness_by_hour = defaultdict(list)
        presence_by_area_hour = defaultdict(lambda: defaultdict(int))

        for entry in self.history:
            ts = entry.get("timestamp", time.time())
            hour = datetime.fromtimestamp(ts).hour
            if entry.get("event_type") == "presence":
                area = entry.get("area")
                presence_by_area_hour[area][hour] += 1
            else:
                state = entry.get("state") or {}
                if isinstance(state, dict):
                    bri = state.get("brightness")
                    if bri is not None:
                        brightness_by_hour[hour].append(bri)

        avg_brightness_by_hour = {
            hour: sum(vals) / len(vals) for hour, vals in brightness_by_hour.items()
        }
        presence_stats = {area: dict(hours) for area, hours in presence_by_area_hour.items()}

        return {
            "avg_brightness_by_hour": avg_brightness_by_hour,
            "presence_by_area_hour": presence_stats,
        }


_global_learner = AdaptiveLearner()


def get_learner() -> AdaptiveLearner:
    return _global_learner


@service
def suggest_rules():
    """Service to print learned patterns as YAML."""
    patterns = _global_learner.analyze_patterns()
    snippet = yaml.safe_dump(patterns)
    log.info(snippet)
    return snippet

