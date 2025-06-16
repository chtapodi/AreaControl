import yaml
from datetime import datetime
from astral import LocationInfo
from astral.sun import azimuth, elevation
import pytz
import math

try:
    pyscript_compile
except NameError:  # pragma: no cover - running outside Pyscript
    def pyscript_compile(func):
        return func


class SunTracker:
    """Track the sun position and determine if areas face the sun."""

    def __init__(self, config_path):
        self.config_path = config_path
        self.reload_config()

    @pyscript_compile
    def reload_config(self):
        with open(self.config_path, "r") as f:
            self.config = yaml.safe_load(f) or {}
        loc = self.config.get("location", {})
        latitude = loc.get("latitude", 0.0)
        longitude = loc.get("longitude", 0.0)
        self.location = LocationInfo(latitude=latitude, longitude=longitude)
        self.tz = pytz.timezone(self.location.timezone)
        self.areas = self.config.get("areas", {})

        self.default_light_distance = self.config.get("max_light_distance", 0.3048)

    def get_sun_position(self, when=None):
        """Return current sun azimuth and altitude."""
        when = when or datetime.now(tz=self.tz)
        observer = self.location.observer
        return azimuth(observer, when), elevation(observer, when)

    def is_area_facing_sun(self, area_name, when=None, tolerance=45):
        """Return True if the given area is facing the sun."""
        area = self.areas.get(area_name)
        if area is None:
            return False
        bearing = area.get("bearing")
        if bearing is None:
            return False
        az, alt = self.get_sun_position(when)
        if alt <= 0:
            return False
        diff = abs((az - bearing + 180) % 360 - 180)
        return diff <= tolerance

    def recommended_blind_closure(
        self,
        area_name,
        window_height,
        max_light_distance=None,
        when=None,
        tolerance=45,
    ):
        """Return the percentage that the blind should be closed.

        Parameters:
            area_name (str): Name of the window/area.
            window_height (float): Height of the window in meters.
            max_light_distance (float, optional): Maximum patch of light allowed
                on the floor from the window. Defaults to the config value or
                about one foot (0.3048m).
            when (datetime, optional): Time for the calculation. Defaults to now.
            tolerance (int, optional): Bearing tolerance in degrees.

        Returns:
            float: Recommended closure percentage in the range [0.0, 1.0].
        """
        if max_light_distance is None:
            max_light_distance = self.default_light_distance

        if not self.is_area_facing_sun(area_name, when=when, tolerance=tolerance):
            return 0.0

        _, alt = self.get_sun_position(when)
        if alt <= 0:
            return 0.0

        # Amount of window height that can remain uncovered without exceeding
        # the allowed patch length on the floor.
        allowed_open = max_light_distance * math.tan(math.radians(alt))

        coverage_height = window_height - allowed_open
        percentage = coverage_height / window_height
        return max(0.0, min(1.0, percentage))

    def closure_for_area(self, area_name, when=None, tolerance=45):
        """Convenience wrapper using window info from the config."""
        area = self.areas.get(area_name, {})
        height = area.get("window_height")
        if height is None:
            return 0.0
        max_dist = area.get("max_light_distance", self.default_light_distance)
        return self.recommended_blind_closure(area_name, height, max_dist, when=when, tolerance=tolerance)

