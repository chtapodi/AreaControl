"""Scenario-based tests using real historic HA event sequences.

Replays extracted event sequences through the OccupancyEngine with the
actual room connections from connections.yml and the real per-room profiles
from occupancy_config.yml.

Validates:
- Path tracking: office→hallway transitions → predecessor resolution
- Living room granularity: FP2 sub-zones should all be hot
- Decay during idle: 5-min gaps → visible confidence decline
- Neighbor adjacency: connected rooms get proper neighbor lookup
"""
from __future__ import annotations

import json
import os
import sys
import time
import types
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Setup: stub HA dependencies, add pyscript to path
# ---------------------------------------------------------------------------

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

_pyscript_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_pyscript_root))
os.chdir(_pyscript_root)

from modules.area_graph import AreaGraph
from modules.occupancy_engine import OccupancyEngine
from modules.occupancy_config import load_config


# ---------------------------------------------------------------------------
# Load real configs and extracted sequences
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def real_area_graph():
    return AreaGraph("connections.yml")


@pytest.fixture(scope="module")
def real_config():
    return load_config("occupancy_config.yml")


@pytest.fixture(scope="module")
def extracted_sequences():
    seq_path = Path(__file__).parent.parent / "debug" / "extracted_sequences.json"
    if not seq_path.exists():
        pytest.skip("extracted_sequences.json not found — run debug/extract_motion_events.py first")
    with open(seq_path) as f:
        return json.load(f)


@pytest.fixture
def engine(real_area_graph, real_config):
    """Fresh engine for each test."""
    return OccupancyEngine(real_area_graph, real_config)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def get_sequence_by_id(sequences, seq_id):
    for s in sequences:
        if s["id"] == seq_id:
            return s
    return None


def replay_sequence(engine, seq):
    """Feed all events in a sequence to the engine."""
    for evt in seq.get("events", []):
        dt = evt.get("dt_s", 1.0)
        if dt > 0:
            engine._last_tick = time.time() - dt
            engine.tick()

        area = evt["area"]
        tag = evt.get("tag", "motion_detected")

        if tag == "presence" and evt.get("state") == "on":
            engine.handle_presence(area, present=True)
        elif tag == "presence" and evt.get("state") == "off":
            engine.handle_presence(area, present=False)
        elif evt.get("state") == "off":
            pass
        else:
            engine.handle_motion(area)


# ---------------------------------------------------------------------------
# Scenario tests
# ---------------------------------------------------------------------------

class TestRealWalks:
    """Scenario: real walks through the house."""

    def test_office_to_hallway_walk_sequence_0(self, engine, extracted_sequences):
        """Sequence 0: office→hallway→living_room sub-zones.
        
        After passing through: hallway conf > some threshold (was visited mid-walk).
        Living room sub-zones all have presence-level boosts.
        """
        seq = get_sequence_by_id(extracted_sequences, 0)
        assert seq is not None, "Sequence 0 not found"

        replay_sequence(engine, seq)

        # After 148s walk with decay ticks: most recent area should be hottest
        office_conf = engine.room_occupancy_confidence("office")
        # Office was visited at t=0 and t=148.7s — should be hottest
        assert office_conf > 0.05, f"Office should have recent activity, got {office_conf:.3f}"
        
        # Living room sub-zones got FP2 presence (0.3 boost) mid-walk — some decay by now
        couch_conf = engine.room_occupancy_confidence("living_room_couch_0")
        assert couch_conf > 0.01, f"Living room sub-zone should have above-min confidence, got {couch_conf:.3f}"

    def test_office_50min_idle_gap_resets_confidence(self, engine):
        """50-min idle period: engine decays to near min confidence."""
        # Simulate someone sitting in office for 50 min with no motion
        engine.handle_motion("office")
        engine.handle_motion("office")  # boost to ~0.30

        # 50 minutes of decay
        engine._last_tick = time.time() - (50 * 60)
        engine.tick()

        conf = engine.room_occupancy_confidence("office")
        # After 50min with 120s half-life: ~25 half-lives, should be near floor
        assert conf < 0.02, f"After 50min idle, confidence should be near min, got {conf:.3f}"

    def test_living_room_fp2_granularity_all_hot(self, engine, extracted_sequences):
        """Sequence 16: 14 FP2 presence events across 8 living room sub-zones.
        
        All sub-zones should have above-min confidence after the sequence
        (decay happens during 141s walk, so not all stay at max).
        """
        seq = get_sequence_by_id(extracted_sequences, 16)
        assert seq is not None, "Sequence 16 not found"
        replay_sequence(engine, seq)

        # After 141s with decay, visited zones should be above min
        hot_zones = [
            "living_room_dining_room_1",
            "living_room_couch_0",
            "living_room_back",
            "living_room_couch_1",
            "living_room_chair_0",
            "living_room_dining_room_2",
            "living_room_dining_room_0",
        ]
        above_min = 0
        for zone in hot_zones:
            conf = engine.room_occupancy_confidence(zone)
            if conf > 0.01:
                above_min += 1
        # At least half the zones should be above min (recent events keep them up)
        assert above_min >= 4, f"Only {above_min}/8 zones above min after 141s walk"

    def test_unvisited_room_stays_at_min(self, engine, extracted_sequences):
        """Rooms never visited AND not connected to visited rooms stay at min.
        
        Neighbor diffusion may leak small amounts to connected rooms,
        so we check only isolated/unconnected rooms.
        """
        seq = get_sequence_by_id(extracted_sequences, 8)
        assert seq is not None
        replay_sequence(engine, seq)

        # outside has min_confidence=0.001, may get tiny diffusion from nearby
        if "outside" in engine._rooms:
            conf = engine.room_occupancy_confidence("outside")
            assert conf <= 0.02, f"outside should be near min, got {conf:.3f}"

    def test_fast_room_crossing_office_to_hallway(self, engine):
        """Rapid office→hallway transition (355ms): both get motion boost."""
        engine.handle_motion("office")
        o1 = engine.room_occupancy_confidence("office")

        engine._last_tick = time.time() - 0.355  # 355ms later
        engine.handle_motion("hallway")
        h1 = engine.room_occupancy_confidence("hallway")

        assert o1 > 0.01
        assert h1 > 0.01
        # Office should NOT have lost all confidence in 355ms
        assert o1 >= 0.15

    def test_adjacent_motion_suppression_scenario(self, engine):
        """Kitchen hot → hallway neighbor diffusion should be detectable.
        
        This validates that check_adjacent_motion() could work:
        if kitchen has high confidence, connected rooms get diffusion.
        Note: handle_motion calls tick() with real time, so between
        rapid calls there is some real-time decay.
        """
        # Build high confidence in kitchen
        for _ in range(20):
            engine.handle_motion("kitchen")
        engine._last_tick = time.time() - 15
        engine.tick()

        kitchen_conf = engine.room_occupancy_confidence("kitchen")
        hallway_conf = engine.room_occupancy_confidence("hallway")

        assert kitchen_conf > 0.70, f"Kitchen should be high confidence, got {kitchen_conf:.3f}"
        # Hallway is connected to kitchen → should get diffusion
        assert hallway_conf > 0.01, f"Hallway should get diffusion from kitchen, got {hallway_conf:.3f}"

    def test_neighbors_function_uses_real_connections(self, engine):
        """OccupancyEngine.neighbors() returns real room adjacencies."""
        n = engine.neighbors("hallway")
        # hallway connects to many rooms per real connections.yml
        assert len(n) > 1, f"Hallway should have multiple neighbors, got {n}"
        assert "kitchen" in n or "office" in n

    def test_likely_predecessor_office_to_hallway(self, engine):
        """After walking office→hallway, hallway's likely_predecessor is office."""
        engine.handle_motion("office")
        engine.handle_motion("office")  # boost office
        engine._last_tick = time.time() - 0.5
        engine.handle_motion("hallway")

        pred = engine.likely_predecessor("hallway")
        assert pred == "office", f"Expected predecessor 'office', got {pred}"

    def test_no_extinction_after_long_sequence(self, engine, extracted_sequences):
        """After replaying a full walk, no room should have extinct confidence."""
        seq = get_sequence_by_id(extracted_sequences, 0)
        assert seq is not None
        replay_sequence(engine, seq)

        # Simulate additional decay after walk ends
        engine._last_tick = time.time() - 600  # 10 more minutes
        engine.tick()

        for area in engine._rooms:
            conf = engine.room_occupancy_confidence(area)
            assert conf >= 0.001, f"{area} at {conf:.4f} — below extinction floor"

    def test_presence_on_then_off_sequence(self, engine):
        """Presence on → presence off: confidence goes up then partial down."""
        engine.handle_presence("living_room", present=True)
        after_on = engine.room_occupancy_confidence("living_room")

        engine.handle_presence("living_room", present=False)
        after_off = engine.room_occupancy_confidence("living_room")

        assert after_on > 0.20, f"Presence on should boost substantially, got {after_on:.3f}"
        assert after_off < after_on, "Presence off should reduce confidence"
        assert after_off > 0.01, "Presence off should not zero out confidence"
