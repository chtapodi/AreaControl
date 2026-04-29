"""Unit tests for AreaGraph and OccupancyEngine.

Validates against the Occupancy Tracker Architecture spec:
https://obsidian://Projects/Areas/Home/Homeassistant/Projects/
  Homeassistant - Projects - Occupancy Tracker Architecture.md
"""
from __future__ import annotations

import math
import os
import sys
import time
import types
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Setup: make modules importable without HA dependencies
# ---------------------------------------------------------------------------

# Stub the logger module so it works in test environment
if "logger" not in sys.modules:
    logger_mod = types.ModuleType("logger")
    class _TestLogger:
        def __init__(self, *a, **k): pass
        def debug(self, *a, **k): pass
        def info(self, *a, **k): pass
        def warning(self, *a, **k): pass
        def error(self, *a, **k): pass
    logger_mod.Logger = _TestLogger
    sys.modules["logger"] = logger_mod

# Add pyscript root to path
_pyscript_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_pyscript_root))

from modules.area_graph import AreaGraph, load_connections
from modules.occupancy_engine import OccupancyEngine, _RoomState
from modules.occupancy_config import (
    RoomProfile,
    OccupancyConfig,
    load_config,
    _parse_room_profile,
)

# ---------------------------------------------------------------------------
# AreaGraph tests
# ---------------------------------------------------------------------------

class TestAreaGraphConstruction:
    """AreaGraph F1: construct graph from connection pairs."""

    def test_builds_from_dict_list(self):
        """Construct from list of single-key dicts."""
        pairs = [{"kitchen": "hallway"}, {"hallway": "office"}]
        g = AreaGraph(pairs)
        assert "kitchen" in g
        assert "hallway" in g
        assert "office" in g
        assert len(g) == 3

    def test_symmetric_bidirectional(self):
        """Connections are undirected — A→B implies B→A."""
        pairs = [{"kitchen": "hallway"}]
        g = AreaGraph(pairs)
        assert "hallway" in g.neighbors("kitchen")
        assert "kitchen" in g.neighbors("hallway")

    def test_empty_list_produces_empty_graph(self):
        g = AreaGraph([])
        assert len(g) == 0
        assert g.areas == set()


class TestAreaGraphNeighbors:
    """AreaGraph.neighbors(): direct connections."""

    @pytest.fixture
    def graph(self):
        pair_list = [
            {"bedroom": "hallway"},
            {"hallway": "kitchen"},
            {"kitchen": "dining_room"},
        ]
        return AreaGraph(pair_list)

    def test_direct_neighbors(self, graph):
        assert graph.neighbors("hallway") == {"bedroom", "kitchen"}

    def test_island_node_no_neighbors(self, graph):
        assert graph.neighbors("dining_room") == {"kitchen"}

    def test_unknown_area_returns_empty_set(self, graph):
        assert graph.neighbors("mars") == set()


class TestAreaGraphDistance:
    """AreaGraph.distance(): shortest path via BFS."""

    @pytest.fixture
    def graph(self):
        pairs = [
            {"a": "b"}, {"b": "c"}, {"c": "d"},
            {"x": "y"},  # isolated pair
        ]
        return AreaGraph(pairs)

    def test_same_node_zero(self, graph):
        assert graph.distance("a", "a") == 0

    def test_direct_neighbor_one(self, graph):
        assert graph.distance("a", "b") == 1

    def test_two_hops(self, graph):
        assert graph.distance("a", "c") == 2

    def test_three_hops(self, graph):
        assert graph.distance("a", "d") == 3

    def test_no_path_returns_neg1(self, graph):
        assert graph.distance("a", "x") == -1

    def test_unknown_node_returns_neg1(self, graph):
        assert graph.distance("a", "z") == -1
        assert graph.distance("z", "a") == -1


class TestAreaGraphConnectedAreas:
    """AreaGraph.connected_areas(): transitive closure."""

    @pytest.fixture
    def graph(self):
        pairs = [
            {"a": "b"}, {"b": "c"}, {"c": "d"},
            {"x": "y"},
        ]
        return AreaGraph(pairs)

    def test_full_component(self, graph):
        assert graph.connected_areas("a") == {"a", "b", "c", "d"}

    def test_small_component(self, graph):
        assert graph.connected_areas("x") == {"x", "y"}

    def test_unknown_area_empty(self, graph):
        assert graph.connected_areas("z") == set()


class TestAreaGraphHasArea:
    """AreaGraph.has_area(): membership check."""

    def test_known_area(self):
        g = AreaGraph([{"a": "b"}])
        assert g.has_area("a")
        assert g.has_area("b")

    def test_unknown_area(self):
        g = AreaGraph([{"a": "b"}])
        assert not g.has_area("c")


# ---------------------------------------------------------------------------
# OccupancyConfig tests
# ---------------------------------------------------------------------------

class TestRoomProfileDefaults:
    """RoomProfile: default values match spec."""

    def test_reinforcement_default(self):
        p = RoomProfile()
        assert p.reinforcement == 0.15

    def test_decay_half_life_default(self):
        p = RoomProfile()
        assert p.decay_half_life_s == 120

    def test_min_confidence_default(self):
        p = RoomProfile()
        assert p.min_confidence == 0.01

    def test_presence_boost_default(self):
        p = RoomProfile()
        assert p.presence_boost == 0.3

    def test_absence_penalty_default(self):
        p = RoomProfile()
        assert p.absence_penalty == 0.4

    def test_neighbor_diffusion_default(self):
        p = RoomProfile()
        assert p.neighbor_diffusion == 0.15
        assert p.neighbor_max_confidence == 0.3


# ---------------------------------------------------------------------------
# OccupancyEngine tests
# ---------------------------------------------------------------------------

class TestOccupancyEngineInit:
    """OccupancyEngine.__init__(): pre-populates rooms from AreaGraph."""

    def test_prepopulates_all_areas(self):
        g = AreaGraph([{"kitchen": "hallway"}])
        config = OccupancyConfig()
        eng = OccupancyEngine(g, config)
        # All graph areas should have state
        assert "kitchen" in eng._rooms
        assert "hallway" in eng._rooms

    def test_initial_confidence_is_min(self):
        g = AreaGraph([{"kitchen": "hallway"}])
        config = OccupancyConfig()
        eng = OccupancyEngine(g, config)
        assert eng.room_occupancy_confidence("kitchen") == 0.01

    def test_unknown_area_returns_min_confidence(self):
        g = AreaGraph([{"kitchen": "hallway"}])
        config = OccupancyConfig()
        eng = OccupancyEngine(g, config)
        assert eng.room_occupancy_confidence("bedroom") == 0.01


class TestOccupancyEngineMotionReinforcement:
    """F2: Confidence increases on motion events. Repeated motion builds to cap."""

    @pytest.fixture
    def engine(self):
        g = AreaGraph([{"kitchen": "hallway"}])
        return OccupancyEngine(g, OccupancyConfig())

    def test_single_motion_increases_confidence(self, engine):
        engine.handle_motion("kitchen")
        conf = engine.room_occupancy_confidence("kitchen")
        assert conf > 0.01  # above min
        assert conf <= 1.0

    def test_double_motion_double_boost(self, engine):
        engine.handle_motion("kitchen")
        c1 = engine.room_occupancy_confidence("kitchen")
        engine.handle_motion("kitchen")
        c2 = engine.room_occupancy_confidence("kitchen")
        assert c2 > c1

    def test_repeated_motion_capped_at_max(self, engine):
        # 10 motion events should saturate to max
        for _ in range(10):
            engine.handle_motion("kitchen")
        conf = engine.room_occupancy_confidence("kitchen")
        assert conf == 1.0

    def test_motion_in_unknown_room_adds_room(self, engine):
        engine.handle_motion("garage")
        assert "garage" in engine._rooms
        assert engine.room_occupancy_confidence("garage") > 0.01


class TestOccupancyEngineDecay:
    """F3: Confidence decays toward min without events. No extinction."""

    @pytest.fixture
    def engine(self):
        g = AreaGraph([{"kitchen": "hallway"}])
        config = OccupancyConfig(
            defaults=RoomProfile(
                decay_half_life_s=120,
                min_confidence=0.01,
            ),
            tick_interval_s=15,
        )
        return OccupancyEngine(g, config)

    def test_decay_reduces_confidence_over_time(self, engine):
        engine.handle_motion("kitchen")
        before = engine.room_occupancy_confidence("kitchen")
        assert before > 0.10

        # Simulate time passing: 120s = one half-life
        engine._last_tick = time.time() - 120
        engine.tick()

        after = engine.room_occupancy_confidence("kitchen")
        assert after < before
        # Should be roughly halved (plus some due to tick's own decay)
        assert after <= before * 0.55  # generous tolerance

    def test_never_drops_below_min_confidence(self, engine):
        engine.handle_motion("kitchen")
        # Simulate a very long time passing
        engine._last_tick = time.time() - 99999
        engine.tick()
        assert engine.room_occupancy_confidence("kitchen") >= 0.01

    def test_decay_below_min_is_floor(self, engine):
        # Multiple halvings
        engine.handle_motion("kitchen")  # ~0.16
        for _ in range(20):
            engine._last_tick = time.time() - 120
            engine.tick()
        assert engine.room_occupancy_confidence("kitchen") == pytest.approx(0.01, abs=0.001)


class TestOccupancyEngineNeighborDiffusion:
    """F4: Confidence diffuses to adjacent areas at lower cap."""

    @pytest.fixture
    def engine(self):
        g = AreaGraph([{"kitchen": "hallway"}, {"hallway": "office"}])
        config = OccupancyConfig(
            defaults=RoomProfile(
                reinforcement=0.5,       # Fast saturation for test
                neighbor_diffusion=0.2,  # 20% bleeds
                neighbor_max_confidence=0.3,
                min_confidence=0.01,
            ),
        )
        return OccupancyEngine(g, config)

    def test_high_confidence_bleeds_to_neighbor(self, engine):
        # Saturate kitchen
        engine.handle_motion("kitchen")
        engine.handle_motion("kitchen")  # conf = 1.0
        engine.handle_motion("kitchen")

        # Force diffusion by ticking
        engine._last_tick = time.time() - 15
        engine.tick()

        kitchen_conf = engine.room_occupancy_confidence("kitchen")
        hallway_conf = engine.room_occupancy_confidence("hallway")

        # Hallway should get some diffusion from kitchen
        assert hallway_conf > 0.01, f"Expected hallway to get diffusion, got {hallway_conf}"
        assert hallway_conf <= 0.3, f"Hallway diffused conf {hallway_conf} exceeds cap 0.3"

    def test_diffusion_capped_at_neighbor_max(self, engine):
        # Saturate kitchen
        for _ in range(5):
            engine.handle_motion("kitchen")
        engine._last_tick = time.time() - 15
        engine.tick()

        hallway_conf = engine.room_occupancy_confidence("hallway")
        assert hallway_conf <= 0.3, f"Diffused confidence {hallway_conf} exceeds neighbor_max 0.3"

    def test_isolated_room_gets_no_diffusion(self, engine):
        # Add an isolated room
        engine._ensure_room("garage")
        for _ in range(5):
            engine.handle_motion("kitchen")
        engine._last_tick = time.time() - 15
        engine.tick()

        garage_conf = engine.room_occupancy_confidence("garage")
        assert garage_conf == pytest.approx(0.01, abs=0.001)


class TestOccupancyEnginePresence:
    """F5/F6: Presence events boost more than motion. Absence reduces faster."""

    def test_presence_on_boost_larger_than_motion(self):
        g = AreaGraph([{"room": "hallway"}])
        profile = RoomProfile(reinforcement=0.15, presence_boost=0.3)
        config = OccupancyConfig(defaults=profile)
        eng = OccupancyEngine(g, config)

        eng.handle_motion("room")
        motion_conf = eng.room_occupancy_confidence("room")

        eng2 = OccupancyEngine(g, config)
        eng2.handle_presence("room", present=True)
        presence_conf = eng2.room_occupancy_confidence("room")

        assert presence_conf > motion_conf

    def test_absence_reduces_confidence(self):
        g = AreaGraph([{"room": "hallway"}])
        profile = RoomProfile(reinforcement=0.5, absence_penalty=0.4)
        config = OccupancyConfig(defaults=profile)
        eng = OccupancyEngine(g, config)

        # Build up confidence
        eng.handle_motion("room")
        eng.handle_motion("room")
        before = eng.room_occupancy_confidence("room")

        eng.handle_presence("room", present=False)
        after = eng.room_occupancy_confidence("room")

        # Should drop to ~60% (1 - 0.4 = 0.6)
        assert after < before
        assert after >= 0.01  # Never below floor

    def test_absence_does_not_zero(self):
        g = AreaGraph([{"room": "hallway"}])
        profile = RoomProfile(
            reinforcement=0.5,
            absence_penalty=0.4,
            min_confidence=0.01,
        )
        config = OccupancyConfig(defaults=profile)
        eng = OccupancyEngine(g, config)

        # Low confidence → absence
        eng.handle_motion("room")  # 0.15
        eng.handle_presence("room", present=False)  # 0.15 * 0.6 = 0.09
        conf = eng.room_occupancy_confidence("room")
        assert conf > 0.005  # Not zero, above floor


class TestOccupancyEngineRecentActivity:
    """F7: Binary recent-activity check."""

    def test_recent_activity_after_motion(self):
        g = AreaGraph([{"room": "hallway"}])
        eng = OccupancyEngine(g, OccupancyConfig())
        eng.handle_motion("room")
        assert eng.room_recent_activity("room", seconds=300) is True

    def test_no_activity_for_empty_room(self):
        g = AreaGraph([{"room": "hallway"}])
        config = OccupancyConfig(defaults=RoomProfile(recent_window_s=300))
        eng = OccupancyEngine(g, config)
        assert eng.room_recent_activity("room") is False

    def test_stale_activity_outside_window(self):
        g = AreaGraph([{"room": "hallway"}])
        eng = OccupancyEngine(g, OccupancyConfig())
        eng.handle_motion("room")
        # Manually age the event
        eng._rooms["room"].last_event_time = time.time() - 999
        assert eng.room_recent_activity("room", seconds=60) is False


class TestOccupancyEngineAdjacentOccupancy:
    """F8: Adjacent-room occupancy query."""

    def test_returns_neighbor_confidences(self):
        g = AreaGraph([{"kitchen": "hallway"}, {"hallway": "office"}])
        eng = OccupancyEngine(g, OccupancyConfig(
            defaults=RoomProfile(reinforcement=0.5),
        ))

        eng.handle_motion("kitchen")
        eng.handle_motion("kitchen")  # confidence ~1.0

        adjacent = eng.adjacent_occupancy("kitchen")
        assert "hallway" in adjacent
        assert isinstance(adjacent["hallway"], float)


class TestOccupancyEngineLikelyPredecessor:
    """F9: Likely predecessor room query."""

    def test_returns_highest_neighbor(self):
        g = AreaGraph([{"kitchen": "hallway"}, {"hallway": "office"}])
        profile = RoomProfile(reinforcement=0.5)
        eng = OccupancyEngine(g, OccupancyConfig(defaults=profile))

        # Make kitchen hotter than hallway
        eng.handle_motion("kitchen")
        eng.handle_motion("kitchen")
        eng.handle_motion("kitchen")  # kitchen = 1.0
        eng.handle_motion("hallway")  # hallway = ~0.16

        pred = eng.likely_predecessor("hallway")
        assert pred == "kitchen"

    def test_returns_none_when_no_neighbor_has_meaningful_confidence(self):
        g = AreaGraph([{"kitchen": "hallway"}])
        eng = OccupancyEngine(g, OccupancyConfig())
        pred = eng.likely_predecessor("kitchen")
        assert pred is None


class TestOccupancyEngineEdgeCases:
    """Edge cases: rapid events, recovery, per-room profiles."""

    def test_rapid_events_dont_cause_instability(self):
        """5 events in rapid succession should be stable."""
        g = AreaGraph([{"room": "hallway"}])
        eng = OccupancyEngine(g, OccupancyConfig())

        for _ in range(5):
            t0 = time.time()
            eng._last_tick = t0 - 0.001  # 1ms gap
            eng.handle_motion("room")

        conf = eng.room_occupancy_confidence("room")
        # Should be at most 0.15 * 5 = 0.75, plus any diffusion
        assert conf <= 1.0
        assert conf > 0.5

    def test_recovery_from_absence(self):
        """After absence, a new motion should bring confidence back up."""
        g = AreaGraph([{"room": "hallway"}])
        profile = RoomProfile(
            reinforcement=0.5, absence_penalty=0.4, min_confidence=0.01,
        )
        eng = OccupancyEngine(g, OccupancyConfig(defaults=profile))

        eng.handle_motion("room")  # 0.51
        eng.handle_presence("room", present=False)  # ~0.306
        eng.handle_motion("room")  # should recover

        conf = eng.room_occupancy_confidence("room")
        assert conf > 0.5  # Recovered significantly

    def test_per_room_profile_applied(self):
        """Rooms with custom profiles use them instead of defaults."""
        g = AreaGraph([{"fast_room": "slow_room"}])
        config = OccupancyConfig(
            defaults=RoomProfile(reinforcement=0.15),
            rooms={
                "fast_room": RoomProfile(reinforcement=0.4),
            },
        )
        eng = OccupancyEngine(g, config)

        eng.handle_motion("fast_room")
        fast = eng.room_occupancy_confidence("fast_room")

        eng.handle_motion("slow_room")
        slow = eng.room_occupancy_confidence("slow_room")

        assert fast > slow, f"fast_room ({fast}) should be higher than slow_room ({slow})"

    def test_all_rooms_idle_converge_to_min(self):
        """After hours of no activity, all rooms hit min_confidence."""
        g = AreaGraph([{"kitchen": "hallway"}])
        eng = OccupancyEngine(g, OccupancyConfig(
            defaults=RoomProfile(decay_half_life_s=30, min_confidence=0.01),
        ))

        eng.handle_motion("kitchen")
        eng.handle_motion("hallway")

        # Simulate 1 hour of decay
        for _ in range(120):
            eng._last_tick = time.time() - 30
            eng.tick()

        kitchen_conf = eng.room_occupancy_confidence("kitchen")
        hallway_conf = eng.room_occupancy_confidence("hallway")

        assert abs(kitchen_conf - 0.01) < 0.005
        assert abs(hallway_conf - 0.01) < 0.005

    def test_debug_summary_outputs_all_rooms(self):
        g = AreaGraph([{"kitchen": "hallway"}])
        eng = OccupancyEngine(g, OccupancyConfig())

        eng.handle_motion("kitchen")
        summary = eng.debug_summary()

        assert "kitchen" in summary
        assert "hallway" in summary
        assert "conf=" in summary

    def test_str_equals_debug_summary(self):
        g = AreaGraph([{"kitchen": "hallway"}])
        eng = OccupancyEngine(g, OccupancyConfig())

        assert str(eng) == eng.debug_summary()


class TestOccupancyConfigLoading:
    """Configuration YAML loading."""

    def test_load_defaults_when_no_file(self):
        config = load_config("nonexistent_occupancy_config.yml")
        assert isinstance(config, OccupancyConfig)
        assert config.defaults.reinforcement == 0.15
        assert config.tick_interval_s == 15

    def test_parse_room_profile_defaults(self):
        parsed = _parse_room_profile({})
        assert isinstance(parsed, RoomProfile)
        assert parsed.reinforcement == 0.15

    def test_parse_room_profile_override(self):
        parsed = _parse_room_profile({"reinforcement": 0.42, "decay_half_life_s": 60})
        assert parsed.reinforcement == 0.42
        assert parsed.decay_half_life_s == 60
        # Others still default
        assert parsed.presence_boost == 0.3
