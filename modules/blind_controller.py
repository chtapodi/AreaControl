from datetime import datetime
from .sun_tracker import SunTracker

try:
    cover
except NameError:
    class DummyCover:
        def set_cover_position(self, **kwargs):
            print("set_cover_position", kwargs)

    cover = DummyCover()

try:
    state
except NameError:
    class DummyState:
        def get(self, *_, **__):
            return None

    state = DummyState()

try:
    log
except NameError:
    from logger import get_logger
    log = get_logger(__name__)


class BlindDriver:
    """Simple driver for Home Assistant cover devices."""

    def __init__(self, name):
        self.name = name
        self.last_state = {"position": 0}

    def set_position(self, position):
        """Set blind position (0-100)."""
        self.last_state = {"position": position}
        try:
            cover.set_cover_position(entity_id=f"cover.{self.name}", position=position)
        except Exception as e:
            log.warning(f"BlindDriver<{self.name}> failed to set position: {e}")
        return self.last_state

    def get_state(self):
        pos = self.last_state.get("position", 0)
        try:
            state_val = state.get(f"cover.{self.name}.position")
            if state_val is not None:
                pos = state_val
        except Exception:
            pass
        return {"name": self.name, "position": pos}

    def get_valid_state_keys(self):
        return ["position"]


class BlindController:
    """Manage blind closure based on sun position."""

    def __init__(self, sun_tracker: SunTracker, area_name: str, driver: BlindDriver, *, update_interval=300, min_delta=0.05):
        self.sun_tracker = sun_tracker
        self.area_name = area_name
        self.driver = driver
        self.update_interval = update_interval
        self.min_delta = min_delta
        self.last_update = None
        self.last_position = None

    def compute_position(self, when=None):
        area = self.sun_tracker.areas.get(self.area_name, {})
        height = area.get("window_height", 1.0)
        max_dist = self.sun_tracker.default_light_distance
        percent = self.sun_tracker.recommended_blind_closure(self.area_name, height, max_dist, when=when)
        return int(round(percent * 100))

    def update(self, when=None):
        target = self.compute_position(when)
        now = when or datetime.now(tz=self.sun_tracker.tz)
        if self.last_position is not None:
            if abs(target - self.last_position) < self.min_delta * 100:
                return self.last_position
            if self.last_update and (now - self.last_update).total_seconds() < self.update_interval:
                return self.last_position
        self.driver.set_position(target)
        self.last_position = target
        self.last_update = now
        return target
