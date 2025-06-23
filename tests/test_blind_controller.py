import pytz
from datetime import datetime

from modules.blind_controller import BlindController


class DummyDriver:
    def __init__(self):
        self.positions = []

    def set_position(self, position):
        self.positions.append(position)


class DummySunTracker:
    def __init__(self):
        self.areas = {'window': {'window_height': 1.0}}
        self.default_light_distance = 0.3
        self.tz = pytz.utc

    def recommended_blind_closure(self, *a, **k):
        return 0.0


def test_update_uses_recommended_closure(monkeypatch):
    sun = DummySunTracker()
    driver = DummyDriver()
    controller = BlindController(sun, 'window', driver)

    calls = {}

    def fake_closure(area, height, max_dist, when=None):
        calls['args'] = (area, height, max_dist, when)
        return 0.42

    monkeypatch.setattr(sun, 'recommended_blind_closure', fake_closure)
    when = datetime(2023, 1, 1, 12, 0, tzinfo=pytz.utc)
    result = controller.update(when=when)

    assert result == 42
    assert driver.positions == [42]
    assert calls['args'] == ('window', 1.0, sun.default_light_distance, when)


def test_update_rate_limited(monkeypatch):
    sun = DummySunTracker()
    driver = DummyDriver()
    controller = BlindController(sun, 'window', driver, update_interval=10, min_delta=0.1)

    values = [0.2, 0.3, 0.23, 0.5]

    def fake_closure(*a, **k):
        return values.pop(0)

    monkeypatch.setattr(sun, 'recommended_blind_closure', fake_closure)

    t0 = datetime(2023, 1, 1, 12, 0, 0, tzinfo=pytz.utc)
    t1 = datetime(2023, 1, 1, 12, 0, 5, tzinfo=pytz.utc)
    t2 = datetime(2023, 1, 1, 12, 0, 11, tzinfo=pytz.utc)
    t3 = datetime(2023, 1, 1, 12, 0, 25, tzinfo=pytz.utc)

    assert controller.update(when=t0) == 20
    assert controller.update(when=t1) == 20  # rate limited by interval
    assert controller.update(when=t2) == 20  # min_delta prevents update
    assert controller.update(when=t3) == 50
    assert driver.positions == [20, 50]
