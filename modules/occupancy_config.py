"""Configuration types and YAML loading for the occupancy engine.

Defines the per-room profile schema and loads ``occupancy_config.yml``.
"""

from __future__ import annotations

import os
import yaml
from dataclasses import dataclass, field

try:
    from modules.logger import Logger
except ImportError:
    from logger import Logger

log = Logger(__name__, globals().get("log"))


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class RoomProfile:
    """Tunable parameters that control confidence behavior for one room.

    All values are floats in the 0.0–1.0 range except the *half_life*
    parameters, which are in seconds.
    """

    # Confidence reinforcement
    reinforcement: float = 0.15
    """Confidence added on each motion event (0–1)."""

    max_confidence: float = 1.0
    """Hard cap — confidence never exceeds this."""

    # Decay
    decay_half_life_s: float = 120
    """Seconds for confidence to halve with no motion."""

    min_confidence: float = 0.01
    """Floor — confidence never drops below this (prevents full extinction)."""

    # Presence sensor overrides
    presence_boost: float = 0.3
    """Confidence added on explicit ``presence=true`` event."""

    absence_penalty: float = 0.4
    """Multiplier applied to confidence on explicit ``presence=false`` event.

    ``new = old * (1 - absence_penalty)`` so a value of 0.4 drops
    confidence to 60% of its previous value.
    """

    # Neighbour diffusion
    neighbor_diffusion: float = 0.15
    """Fraction of a room's confidence that bleeds to each neighbour."""

    neighbor_max_confidence: float = 0.3
    """Cap for diffused confidence — neighbour confidence never exceeds this."""

    neighbor_decay_half_life_s: float = 30
    """Decay half-life *used only for diffused confidences* (faster)."""

    # Recent activity window (binary query)
    recent_window_s: int = 300
    """Seconds of silence before ``room_recent_activity()`` returns False."""


@dataclass
class OccupancyConfig:
    """Top-level configuration for the OccupancyEngine."""

    defaults: RoomProfile = field(default_factory=RoomProfile)
    """Fallback profile used for rooms without their own entry."""

    rooms: dict[str, RoomProfile] = field(default_factory=dict)
    """Per-room profile overrides — keys are area names."""

    tick_interval_s: int = 15
    """Seconds between internal decay/diffusion ticks.

    Smaller values give smoother decay but more CPU.  15 s works well for
    home automation use.
    """


# ---------------------------------------------------------------------------
# YAML loading
# ---------------------------------------------------------------------------

_DEFAULT_CONFIG_PATH = "occupancy_config.yml"


def _parse_room_profile(data: dict) -> RoomProfile:
    """Build a RoomProfile from a parsed YAML dict, using defaults for
    any missing keys."""
    return RoomProfile(
        reinforcement=data.get("reinforcement", 0.15),
        max_confidence=data.get("max_confidence", 1.0),
        decay_half_life_s=data.get("decay_half_life_s", 120),
        min_confidence=data.get("min_confidence", 0.01),
        presence_boost=data.get("presence_boost", 0.3),
        absence_penalty=data.get("absence_penalty", 0.4),
        neighbor_diffusion=data.get("neighbor_diffusion", 0.15),
        neighbor_max_confidence=data.get("neighbor_max_confidence", 0.3),
        neighbor_decay_half_life_s=data.get("neighbor_decay_half_life_s", 30),
        recent_window_s=data.get("recent_window_s", 300),
    )


def load_config(path: str = _DEFAULT_CONFIG_PATH) -> OccupancyConfig:
    """Load OccupancyConfig from a YAML file.

    If the file doesn't exist, returns a default config with a single info
    log message.  This makes the engine safe to run during development
    without requiring a complete config file.
    """
    if not os.path.exists(path):
        log.info("OccupancyConfig: file not found, using defaults (%s)", path)
        return OccupancyConfig()

    with open(path) as f:
        data = yaml.safe_load(f) or {}

    defaults_data = data.get("defaults", {})
    defaults = _parse_room_profile(defaults_data)

    rooms: dict[str, RoomProfile] = {}
    for name, profile_data in data.get("rooms", {}).items():
        merged = {**defaults_data, **(profile_data or {})}
        rooms[name] = _parse_room_profile(merged)

    tick = data.get("tick_interval_s", 15)

    log.info(
        "OccupancyConfig: loaded %d room profiles (tick=%ds)",
        len(rooms),
        tick,
    )
    return OccupancyConfig(defaults=defaults, rooms=rooms, tick_interval_s=tick)
