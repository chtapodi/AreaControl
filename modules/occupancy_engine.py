"""Anonymous room occupancy confidence engine.

Replaces the legacy TrackManager.  Models per-room occupancy as a
continuous confidence score (0.01–1.0) with exponential decay, event
reinforcement, neighbour diffusion, and no extinction.

Usage::

    engine = OccupancyEngine(area_graph, config)
    engine.handle_motion("kitchen")
    engine.handle_presence("living_room", present=True)
    engine.tick()                     # apply decay + diffusion
    confidence = engine.room_occupancy_confidence("kitchen")
    active = engine.room_recent_activity("hallway")
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field

try:
    from modules.logger import Logger
    from modules.occupancy_config import OccupancyConfig, RoomProfile
    from modules.area_graph import AreaGraph
except ImportError:
    from logger import Logger
    from occupancy_config import OccupancyConfig, RoomProfile
    from area_graph import AreaGraph

log = Logger(__name__, globals().get("log"))


# ---------------------------------------------------------------------------
# Internal per-room state
# ---------------------------------------------------------------------------


@dataclass
class _RoomState:
    """Mutable runtime state for one room."""

    confidence: float = 0.01
    """Current occupancy confidence (clamped to min–max profile range)."""

    last_event_time: float = 0.0
    """Unix timestamp of the most recent motion or presence event."""

    last_tick_time: float = 0.0
    """Unix timestamp of the last time decay+diffusion were applied."""


# ---------------------------------------------------------------------------
# OccupancyEngine
# ---------------------------------------------------------------------------


class OccupancyEngine:
    """Per-room anonymous occupancy tracker.

    Parameters
    ----------
    area_graph : AreaGraph
        Room adjacency graph (used for neighbour queries).
    config : OccupancyConfig
        Per-room profiles and global tick interval.
    """

    def __init__(
        self,
        area_graph: AreaGraph,
        config: OccupancyConfig,
    ) -> None:
        self._graph = area_graph
        self._config = config
        self._tick_interval = config.tick_interval_s
        self._last_tick: float = time.time()
        self._rooms: dict[str, _RoomState] = {}
        ensure = self._ensure_room

        # Pre-populate state for every known area
        for area in area_graph.areas:
            ensure(area)

        log.info(
            "OccupancyEngine: initialised with %d rooms (tick=%ds)",
            len(self._rooms),
            self._tick_interval,
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def tick(self) -> None:
        """Advance time for all rooms — apply decay then diffusion.

        Called automatically by public query methods when sufficient time
        has elapsed.  May also be called explicitly.
        """
        now = time.time()
        dt = now - self._last_tick
        if dt < 0.1:
            return  # skip sub-100ms ticks
        self._last_tick = now
        self._apply_decay(now, dt)
        self._apply_diffusion(now)

    def handle_motion(self, area: str) -> None:
        """A motion sensor fired in *area*.  Reinforces occupancy."""
        self.tick()
        state = self._ensure_room(area)
        if state is None:
            return
        profile = self._profile(area)
        old = state.confidence
        state.confidence = min(old + profile.reinforcement, profile.max_confidence)
        state.last_event_time = time.time()
        log.info(
            "[occupancy] event=motion area=%-20s confidence: %.2f\u2192%.2f (motion boost)",
            area,
            old,
            state.confidence,
        )

    def handle_presence(self, area: str, present: bool) -> None:
        """An explicit presence sensor reading for *area*.

        Parameters
        ----------
        area : str
            Room identifier.
        present : bool
            ``True`` = someone is here (large boost).
            ``False`` = nobody is here (faster confidence drop).
        """
        self.tick()
        state = self._ensure_room(area)
        if state is None:
            return
        profile = self._profile(area)
        old = state.confidence
        if present:
            state.confidence = min(
                old + profile.presence_boost, profile.max_confidence
            )
            state.last_event_time = time.time()
            log.info(
                "[occupancy] event=presence area=%-20s confidence: %.2f\u2192%.2f (presence boost)",
                area,
                old,
                state.confidence,
            )
        else:
            state.confidence = max(
                old * (1.0 - profile.absence_penalty), profile.min_confidence
            )
            log.info(
                "[occupancy] event=absence  area=%-20s confidence: %.2f\u2192%.2f (absence penalty)",
                area,
                old,
                state.confidence,
            )

    def room_occupancy_confidence(self, area: str) -> float:
        """Current occupancy confidence for *area* (0.01–1.0)."""
        self.tick()
        if area not in self._rooms:
            return self._config.defaults.min_confidence
        return self._rooms[area].confidence

    def room_recent_activity(self, area: str, seconds: int | None = None) -> bool:
        """Was there any event in *area* within the recent window?

        Parameters
        ----------
        area : str
            Room identifier.
        seconds : int, optional
            Look-back window.  Defaults to the profile's ``recent_window_s``.

        Returns
        -------
        bool
            ``True`` if an event occurred within the window.
        """
        self.tick()
        state = self._rooms.get(area)
        if state is None:
            return False
        window = seconds if seconds is not None else self._profile(area).recent_window_s
        return (time.time() - state.last_event_time) < window

    def adjacent_occupancy(self, area: str) -> dict[str, float]:
        """Occupancy confidence for rooms directly connected to *area*.

        Returns a dict mapping neighbour name to confidence.
        """
        self.tick()
        result: dict[str, float] = {}
        for neighbor in self._graph.neighbors(area):
            result[neighbor] = self.room_occupancy_confidence(neighbor)
        return result

    def likely_predecessor(self, area: str) -> str | None:
        """Best guess at which room a person came from.

        Returns the neighbour with the highest occupancy confidence that is
        *not* the area itself.  Returns ``None`` if no neighbour has
        meaningful confidence (>0.05).
        """
        self.tick()
        best: str | None = None
        best_conf = 0.0
        for neighbor in self._graph.neighbors(area):
            conf = self.room_occupancy_confidence(neighbor)
            if conf > best_conf:
                best_conf = conf
                best = neighbor
        return best if best_conf > 0.05 else None

    def debug_summary(self) -> str:
        """Multi-line human-readable state dump for logging."""
        self.tick()
        lines: list[str] = []
        for area in sorted(self._rooms.keys()):
            state = self._rooms[area]
            age = time.time() - state.last_event_time
            lines.append(
                f"  {area:24s}  conf={state.confidence:.3f}  "
                f"last_event={age:.0f}s ago"
            )
        return "\n".join(lines)

    def neighbors(self, area: str) -> set[str]:
        """Areas directly connected to *area*.  Delegates to AreaGraph."""
        return self._graph.neighbors(area)

    def __str__(self) -> str:
        return self.debug_summary()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _ensure_room(self, area: str) -> _RoomState | None:
        if area not in self._rooms:
            # Only create rooms for known areas — unknown/misspelled area
            # strings would cause unbounded _rooms dict growth over time.
            if area not in self._graph.areas:
                log.warning(
                    "[occupancy] _ensure_room: unknown area=%s — skipping",
                    area,
                )
                return None
            self._rooms[area] = _RoomState(
                confidence=self._config.defaults.min_confidence,
                last_event_time=0.0,  # zero = never had an event
                last_tick_time=time.time(),
            )
        return self._rooms[area]

    def _profile(self, area: str) -> RoomProfile:
        return self._config.rooms.get(area, self._config.defaults)

    def _apply_decay(self, now: float, dt: float) -> None:
        """Decay all rooms toward ``min_confidence``.

        Uses continuous half-life decay::

            conf = conf * 0.5 ** (dt / half_life)
        """
        for area, state in self._rooms.items():
            profile = self._profile(area)
            if state.confidence <= profile.min_confidence:
                continue
            old = state.confidence
            factor = 0.5 ** (dt / profile.decay_half_life_s)
            state.confidence = max(old * factor, profile.min_confidence)
            if state.confidence != old:
                log.debug(
                    "[occupancy] decay area=%-20s confidence: %.3f\u2192%.3f "
                    "(%.0fs no motion)",
                    area,
                    old,
                    state.confidence,
                    dt,
                )

    def _apply_diffusion(self, now: float) -> None:
        """Bleed a fraction of each room's confidence to neighbours.

        Calculates all diffusion deltas first, then applies them
        simultaneously so cascade effects are capped by
        ``neighbor_max_confidence`` rather than propagating endlessly.
        """
        deltas: dict[str, float] = {}
        for area, state in self._rooms.items():
            profile = self._profile(area)
            if state.confidence <= profile.min_confidence:
                continue
            diffused = state.confidence * profile.neighbor_diffusion
            for neighbor in self._graph.neighbors(area):
                old = deltas.get(neighbor, 0.0)
                deltas[neighbor] = min(
                    old + diffused, profile.neighbor_max_confidence
                )

        for area, boost in deltas.items():
            state = self._ensure_room(area)
            if state is None:
                continue
            profile = self._profile(area)
            old = state.confidence
            state.confidence = min(old + boost, profile.max_confidence)
            if state.confidence != old:
                log.debug(
                    "[occupancy] diffuse area=%-20s confidence: %.3f\u2192%.3f "
                    "(neighbour bleed)",
                    area,
                    old,
                    state.confidence,
                )
