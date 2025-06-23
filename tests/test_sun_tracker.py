import math

import pytest

from modules.sun_tracker import SunTracker


class DummyTracker(SunTracker):
    """Subclass that allows setting fixed sun positions for tests."""
    def __init__(self, az, alt):
        # Use existing config but we will override areas
        super().__init__('sun_config.yml')
        self._test_az = az
        self._test_alt = alt

    def get_sun_position(self, when=None):
        return self._test_az, self._test_alt


@pytest.mark.parametrize(
    "az,alt,area,expected",
    [
        (90, 10, 'window', True),          # facing directly
        (100, 20, 'window', True),         # within tolerance
        (50, 20, 'window', False),         # outside tolerance
        (90, -5, 'window', False),         # sun below horizon
        (90, 10, 'unknown', False),        # area missing
        (90, 10, 'nobearing', False),      # bearing missing
    ],
)
def test_is_area_facing_sun(monkeypatch, az, alt, area, expected):
    tracker = DummyTracker(az, alt)
    tracker.areas = {
        'window': {'bearing': 90},
        'nobearing': {},
    }
    assert tracker.is_area_facing_sun(area, tolerance=15) is expected


def test_recommended_blind_closure_basic(monkeypatch):
    tracker = DummyTracker(90, 45)  # directly facing with 45 deg altitude
    tracker.areas = {'win': {'bearing': 90}}
    result = tracker.recommended_blind_closure('win', window_height=1.0, max_light_distance=0.5, tolerance=5)
    assert result == pytest.approx(0.5)


def test_recommended_blind_closure_various(monkeypatch):
    tracker = DummyTracker(88, 30)
    tracker.areas = {'win': {'bearing': 90}}
    perc = tracker.recommended_blind_closure('win', 1.0, 0.2, tolerance=5)
    expected = (1.0 - 0.2 * math.tan(math.radians(30))) / 1.0
    assert perc == pytest.approx(expected)

    # not facing the sun
    tracker = DummyTracker(40, 30)
    tracker.areas = {'win': {'bearing': 90}}
    assert tracker.recommended_blind_closure('win', 1.0, 0.2, tolerance=5) == 0.0

    # sun below horizon
    tracker = DummyTracker(90, -1)
    tracker.areas = {'win': {'bearing': 90}}
    assert tracker.recommended_blind_closure('win', 1.0, 0.2, tolerance=5) == 0.0
