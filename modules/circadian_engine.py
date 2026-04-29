import yaml
import os
import time
import builtins
from datetime import datetime, timedelta
import math
from typing import Any

from astral.sun import sun as astral_sun


SunTracker: Any
MODULE_DIR = os.path.dirname(__file__) if "__file__" in globals() else os.getcwd()
CONFIG_DIR = os.path.dirname(MODULE_DIR)
if not os.path.exists(os.path.join(CONFIG_DIR, "sun_config.yml")):
    fallback_dir = os.path.join(os.getcwd(), "pyscript")
    if os.path.exists(os.path.join(fallback_dir, "sun_config.yml")):
        CONFIG_DIR = fallback_dir

# Try to import SunTracker, but provide fallback for testing.
# PyScript can load helper modules without standard package context, so support
# both flat-module and package-relative imports.
try:
    from sun_tracker import SunTracker
    SUNTRACKER_AVAILABLE = True
except ImportError:
    try:
        from modules.sun_tracker import SunTracker
        SUNTRACKER_AVAILABLE = True
    except ImportError:
        try:
            from .sun_tracker import SunTracker
            SUNTRACKER_AVAILABLE = True
        except ImportError:
            SUNTRACKER_AVAILABLE = False

            class _FallbackSunTracker:
                def __init__(self, config_path):
                    pass

                def get_solar_progress(self, when=None):
                    # Fallback: simulate solar progress based on time of day
                    if when is None:
                        when = datetime.now()
                    hour = when.hour + when.minute / 60.0
                    # Simple simulation: sunrise at 6, sunset at 18
                    return (hour - 6.0) / 12.0

                def get_circadian_parameters(self, progress=None, when=None):
                    # Fallback parameters
                    if progress is None:
                        progress = self.get_solar_progress(when)

                    if when is None:
                        when = datetime.now()
                    current_minutes = when.hour * 60 + when.minute
                    if current_minutes >= 6 * 60:
                        brightness = 1.0
                    elif current_minutes < 60:
                        brightness = 1.0 - (0.5 * (current_minutes / 60.0))
                    else:
                        brightness = 0.5

                    clamped = max(-1.0, min(2.0, progress))
                    if clamped < 0:
                        return {'brightness': brightness, 'rgb_color': [255, 50, 10], 'use_rgb': True, 'color_temp_k': 2200}
                    elif clamped < 0.4:
                        t = clamped / 0.4
                        return {'brightness': brightness, 'use_rgb': False, 'color_temp_k': 3000 + 1000*t}
                    elif clamped < 0.6:
                        return {'brightness': brightness, 'use_rgb': False, 'color_temp_k': 4000}
                    elif clamped < 1.0:
                        # Afternoon descent: 4000K -> 2200K from peak (progress 0.6) to horizon (progress 0.0)
                        # t=0 at progress=0.6 (4000K), t=1 at progress=0.0 (2200K)
                        t = max(0.0, min(1.0, (0.6 - clamped) / 0.6))
                        return {'brightness': brightness, 'use_rgb': False, 'color_temp_k': int(4000 - 1800 * t)}
                    elif clamped <= 1.0:
                        # progress=1.0 is the horizon snap artifact — treat as 2200K to match post-sunset hold
                        return {'brightness': brightness, 'use_rgb': False, 'color_temp_k': 2200}
                    elif clamped < 1.019:
                        # 0–10 minutes after sunset: hold at the warm CT floor before switching to RGB
                        return {'brightness': brightness, 'use_rgb': False, 'color_temp_k': 2200}
                    elif clamped < 1.5:
                        # Evening: 10 min after sunset -> midnight. Warm RGB ramp.
                        t = (clamped - 1.019) / (1.5 - 1.019)
                        return {'brightness': brightness, 'rgb_color': [255, int(140 - 16*t), int(70 - 27*t)], 'use_rgb': True, 'color_temp_k': 2200}
                    else:
                        # Late night: midnight -> 1am stays at the floor, then deepen.
                        current_hour = when.hour if when is not None else datetime.now().hour
                        if current_hour < 1:
                            return {'brightness': brightness, 'rgb_color': [255, 124, 43], 'use_rgb': True, 'color_temp_k': 2200}
                        return {'brightness': brightness, 'rgb_color': [255, 50, 10], 'use_rgb': True, 'color_temp_k': 2200}

            SunTracker = _FallbackSunTracker

class CircadianEngine:
    """Core engine for circadian lighting calculations."""
    
    def __init__(self, sun_tracker=None, room_config_path=None):
        """Initialize circadian engine.
        
        Args:
            sun_tracker: SunTracker instance. If None, creates one from default config.
            room_config_path: Path to room_config.yml. If None, uses default location.
        """
        self.sun_tracker: Any = None

        if sun_tracker is None:
            # Default sun tracker config path
            sun_config_path = os.path.join(CONFIG_DIR, "sun_config.yml")
            self.sun_tracker = SunTracker(sun_config_path)
        else:
            self.sun_tracker = sun_tracker
        
        self.room_config_path = room_config_path or os.path.join(CONFIG_DIR, "room_config.yml")
        self.room_config = self._load_room_config()
        self.last_update_time = None
        self.update_interval = 900  # 15 minutes in seconds

    def _ensure_sun_tracker(self):
        """Recover if the loader left the tracker unset or invalid."""
        tracker = getattr(self, "sun_tracker", None)
        if tracker is not None and (
            hasattr(tracker, "get_circadian_parameters")
            or hasattr(tracker, "get_solar_progress")
            or hasattr(tracker, "get_sun_position")
        ):
            return tracker

        sun_config_path = os.path.join(CONFIG_DIR, "sun_config.yml")
        tracker = SunTracker(sun_config_path)
        self.sun_tracker = tracker
        return tracker

    def _get_local_datetime(self, when=None):
        if when is not None:
            return when

        tracker = self._ensure_sun_tracker()
        tz = getattr(tracker, "tz", None)
        if tz is not None:
            return datetime.now(tz=tz)
        return datetime.now()

    def _get_sunrise_datetime(self, when=None):
        current = self._get_local_datetime(when)
        tracker = self._ensure_sun_tracker()

        try:
            location = getattr(tracker, "location", None)
            tz = getattr(tracker, "tz", None)
            if location is not None and hasattr(location, "observer"):
                sun_events = astral_sun(location.observer, date=current.date(), tzinfo=tz)
                sunrise = sun_events.get("sunrise")
                if sunrise is not None:
                    return sunrise
        except Exception:
            pass

        return current.replace(hour=6, minute=0, second=0, microsecond=0)

    def _get_sunset_datetime(self, when=None):
        current = self._get_local_datetime(when)
        tracker = self._ensure_sun_tracker()

        try:
            location = getattr(tracker, "location", None)
            tz = getattr(tracker, "tz", None)
            if location is not None and hasattr(location, "observer"):
                sun_events = astral_sun(location.observer, date=current.date(), tzinfo=tz)
                sunset = sun_events.get("sunset")
                if sunset is not None:
                    return sunset
        except Exception:
            pass

        return current.replace(hour=18, minute=0, second=0, microsecond=0)

    def _get_circadian_brightness(self, when=None):
        current = self._get_local_datetime(when)
        sunrise = self._get_sunrise_datetime(current)

        current_seconds = current.hour * 3600 + current.minute * 60 + current.second
        sunrise_seconds = sunrise.hour * 3600 + sunrise.minute * 60 + sunrise.second

        if current_seconds >= sunrise_seconds:
            return 1.0

        if current_seconds < 3600:
            return 1.0 - (0.5 * (current_seconds / 3600.0))

        return 0.5

    def _get_tracker_progress(self, tracker, when=None):
        if hasattr(tracker, "get_solar_progress"):
            return tracker.get_solar_progress(when)

        if hasattr(tracker, "get_sun_position"):
            _azimuth, altitude = tracker.get_sun_position(when)
            if altitude <= 0:
                return -1.0
            return min(1.0, altitude / 90.0)

        if when is None:
            when = datetime.now()
        hour = when.hour + when.minute / 60.0
        return (hour - 6.0) / 12.0

    def _fallback_circadian_parameters(self, progress=None, when=None):
        if progress is None:
            progress = self._get_tracker_progress(self._ensure_sun_tracker(), when)

        brightness = self._get_circadian_brightness(when)
        current = self._get_local_datetime(when)
        sunrise = self._get_sunrise_datetime(current)
        sunset = self._get_sunset_datetime(current)

        clamped = max(-1.0, min(2.0, progress))
        if clamped < 0:
            return {'brightness': brightness, 'rgb_color': [255, 50, 10], 'use_rgb': True, 'color_temp_k': 2200}
        if clamped < 0.4:
            t = clamped / 0.4
            return {'brightness': brightness, 'use_rgb': False, 'color_temp_k': 3000 + 1000*t}
        if clamped < 0.6:
            return {'brightness': brightness, 'use_rgb': False, 'color_temp_k': 4000}
        if clamped < 1.0:
            # Afternoon descent: 4000K -> 2200K from peak (progress 0.6) to horizon (progress 0.0)
            # t=0 at progress=0.6 (4000K), t=1 at progress=0.0 (2200K)
            t = max(0.0, min(1.0, (0.6 - clamped) / 0.6))
            return {'brightness': brightness, 'use_rgb': False, 'color_temp_k': int(4000 - 1800 * t)}
        if clamped <= 1.0:
            # progress=1.0 is the horizon snap artifact — treat as 2200K to match post-sunset hold
            return {'brightness': brightness, 'use_rgb': False, 'color_temp_k': 2200}
        midnight = current.replace(hour=0, minute=0, second=0, microsecond=0)
        if current.hour >= 12:
            midnight = midnight + timedelta(days=1)
        one_am = midnight + timedelta(hours=1)

        ten_min_after_sunset = sunset + timedelta(minutes=10)
        if sunset <= current < ten_min_after_sunset:
            # 0–10 minutes after sunset: hold at the warm CT floor before switching to RGB
            return {'brightness': brightness, 'use_rgb': False, 'color_temp_k': 2200}
        if ten_min_after_sunset <= current < midnight:
            # Evening: 10 min after sunset -> midnight. Warm RGB ramp.
            total = (midnight - ten_min_after_sunset).total_seconds()
            elapsed = (current - ten_min_after_sunset).total_seconds()
            t = elapsed / total if total > 0 else 1.0
            return {'brightness': brightness, 'rgb_color': [255, int(140 - 16*t), int(70 - 27*t)], 'use_rgb': True, 'color_temp_k': 2200}
        if current < one_am:
            # Midnight -> 1am stays at the floor.
            return {'brightness': brightness, 'rgb_color': [255, 124, 43], 'use_rgb': True, 'color_temp_k': 2200}
        if current < sunrise:
            # After 1am and before sunrise, allow the deeper red again.
            return {'brightness': brightness, 'rgb_color': [255, 50, 10], 'use_rgb': True, 'color_temp_k': 2200}

        # Daytime / sunrise edge cases.
        return {'brightness': brightness, 'use_rgb': False, 'color_temp_k': 2200}
        
    def _load_room_config(self):
        """Load room configuration from YAML file."""
        try:
            with builtins.open(self.room_config_path, 'r') as f:
                config = yaml.safe_load(f) or {}
            return config
        except Exception as e:
            print(f"Warning: Could not load room config: {e}")
            return {'defaults': {}, 'rooms': {}, 'presets': {}}
    
    def get_circadian_color(self, progress=None, when=None):
        """Get base circadian color for given solar progress.
        
        Args:
            progress: Solar progress (0.0 to 1.0). If None, calculates from 'when'.
            when: datetime object used if progress is None.
            
        Returns:
            dict: Color state with keys:
                - brightness: float 0.0 to 1.0
                - color_temp: int (mireds) if use_rgb is False
                - rgb_color: list of 3 ints if use_rgb is True
                - use_rgb: bool
        """
        tracker = self._ensure_sun_tracker()
        if hasattr(tracker, "get_circadian_parameters"):
            params = tracker.get_circadian_parameters(progress, when)
        else:
            params = self._fallback_circadian_parameters(progress, when)
        
        brightness = params['brightness']
        use_rgb = params.get('use_rgb', False)
        
        state = {'brightness': brightness}
        
        if use_rgb:
            state['rgb_color'] = params['rgb_color']
        else:
            # Convert Kelvin to mireds (color_temp in Home Assistant)
            color_temp_k = params.get('color_temp_k', 4000)
            # mireds = 1,000,000 / Kelvin
            if color_temp_k > 0:
                state['color_temp'] = int(1000000 / color_temp_k)
            else:
                state['color_temp'] = 250  # Default 4000K
        
        return state
    
    def get_room_adjusted_color(self, base_color, room_name):
        """Apply room-specific adjustments to base color.
        
        Args:
            base_color: dict from get_circadian_color()
            room_name: name of room (must exist in room_config)
            
        Returns:
            dict: Adjusted color state
        """
        if not self.room_config:
            return base_color
        
        rooms = self.room_config.get('rooms', {})
        defaults = self.room_config.get('defaults', {})
        
        room_config = rooms.get(room_name, {})
        
        # Start with base color
        adjusted = base_color.copy()
        
        # Apply brightness factor
        brightness_factor = room_config.get('brightness_factor', 
                                          defaults.get('brightness_factor', 1.0))
        if 'brightness' in adjusted:
            adjusted['brightness'] = min(1.0, adjusted['brightness'] * brightness_factor)
        
        # Apply min/max brightness limits
        max_brightness = room_config.get('max_brightness', 
                                       defaults.get('max_brightness', 255))
        min_brightness = room_config.get('min_brightness',
                                       defaults.get('min_brightness', 20))
        
        # Convert brightness from 0-1 scale to 0-255 for limits
        if 'brightness' in adjusted:
            brightness_255 = adjusted['brightness'] * 255
            brightness_255 = max(min_brightness, min(max_brightness, brightness_255))
            adjusted['brightness'] = brightness_255 / 255.0
        
        # TODO: Implement color_adjustment (hue/saturation/value)
        # This would require RGB<->HSV conversions
        
        return adjusted
    
    def get_preset_color(self, preset_name):
        """Get color for a named preset.
        
        Args:
            preset_name: name of preset (e.g., 'morning', 'evening')
            
        Returns:
            dict: Color state for preset
        """
        presets = self.room_config.get('presets', {})
        preset = presets.get(preset_name, {})
        
        if not preset:
            # Default fallback
            if preset_name == 'morning':
                return {'brightness': 0.8, 'rgb_color': [255, 220, 180]}
            elif preset_name == 'evening':
                return {'brightness': 0.6, 'rgb_color': [255, 190, 130]}
            elif preset_name == 'night':
                return {'brightness': 0.2, 'rgb_color': [255, 100, 30]}
            else:
                return {'brightness': 0.5, 'color_temp': 250}  # 4000K
        
        state = {}
        if 'brightness' in preset:
            state['brightness'] = preset['brightness']
        
        if preset.get('use_rgb', False) and 'rgb_color' in preset:
            state['rgb_color'] = preset['rgb_color']
        elif 'color_temp_k' in preset:
            state['color_temp'] = int(1000000 / preset['color_temp_k'])
        
        return state
    
    def should_update(self, force=False):
        """Check if it's time for a periodic update.
        
        Args:
            force: If True, always returns True
            
        Returns:
            bool: True if should update
        """
        if force:
            return True
        
        if self.last_update_time is None:
            return True
        
        elapsed = time.time() - self.last_update_time
        return elapsed >= self.update_interval
    
    def mark_updated(self):
        """Mark that an update has been performed."""
        self.last_update_time = time.time()
    
    def schedule_periodic_updates(self, update_callback, interval_minutes=15):
        """Set up scheduled updates (to be called from pyscript time_trigger).
        
        Args:
            update_callback: function to call for updates
            interval_minutes: update interval in minutes
            
        Note:
            This doesn't actually schedule anything in pyscript.
            The caller should use @time_trigger with the returned interval.
        """
        self.update_interval = interval_minutes * 60
        return f"cron(*/{interval_minutes} * * * *)"
    
    def get_next_preset(self, room_name, current_preset=None):
        """Get next preset in sequence for room's toggle_presets.
        
        Args:
            room_name: name of room
            current_preset: current preset name or None
            
        Returns:
            str: next preset name
        """
        rooms = self.room_config.get('rooms', {})
        defaults = self.room_config.get('defaults', {})
        
        room_config = rooms.get(room_name, {})
        preset_sequence = room_config.get('toggle_presets',
                                        defaults.get('toggle_presets', ['morning', 'evening', 'night']))
        
        if not preset_sequence:
            return 'morning'
        
        if current_preset is None or current_preset not in preset_sequence:
            return preset_sequence[0]
        
        current_idx = preset_sequence.index(current_preset)
        next_idx = (current_idx + 1) % len(preset_sequence)
        return preset_sequence[next_idx]

# Global instance for easy access
_global_engine = None

def get_circadian_engine(sun_tracker=None, room_config_path=None):
    """Get or create global circadian engine instance."""
    global _global_engine
    if _global_engine is None:
        _global_engine = CircadianEngine(sun_tracker, room_config_path)
    return _global_engine
