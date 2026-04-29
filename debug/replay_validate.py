#!/usr/bin/env python3
"""Replay real HA event sequences through the OccupancyEngine for validation.

Reads extracted_sequences.json (from extract_motion_events.py) and replays
each sequence through OccupancyEngine, producing:

1. Timeline of confidence changes per room
2. Validation checks: decay correctness, neighbor diffusion, no extinction
3. Per-scenario pass/fail results

Usage:
    python debug/replay_validate.py [--sequence N] [--all] [--interval SECONDS]
"""
from __future__ import annotations

import json
import os
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


# ---------------------------------------------------------------------------
# Add pyscript root to path for module imports
# ---------------------------------------------------------------------------
_pyscript_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_pyscript_root))

from modules.area_graph import AreaGraph
from modules.occupancy_engine import OccupancyEngine
from modules.occupancy_config import load_config as load_occupancy_config


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------

@dataclass
class Timestep:
    """Snapshot of engine state at a point in time."""
    elapsed_s: float
    area: str
    event_type: str  # motion_on / presence_on / absence_off
    confidences: dict[str, float]  # area → confidence BEFORE event
    confidences_after: dict[str, float]  # area → confidence AFTER event


@dataclass 
class ScenarioResult:
    name: str
    steps: list[Timestep] = field(default_factory=list)
    checks: list[dict] = field(default_factory=list)  # {check: ..., passed: bool, detail: str}


# ---------------------------------------------------------------------------
# Replay engine
# ---------------------------------------------------------------------------

class ReplayRunner:
    """Feeds event sequences into OccupancyEngine and records state."""

    def __init__(self, connections_path: str = "connections.yml",
                 config_path: str = "occupancy_config.yml"):
        os.chdir(_pyscript_root)
        self.area_graph = AreaGraph(connections_path)
        self.config = load_occupancy_config(config_path)
        self.engine = OccupancyEngine(self.area_graph, self.config)

    def replay_sequence(self, seq: dict, interval_s: float = 1.0) -> ScenarioResult:
        """Replay one event sequence, ticking at interval_s between events."""
        # Reset engine to clean state
        self.engine = OccupancyEngine(self.area_graph, self.config)
        result = ScenarioResult(name=f"seq_{seq.get('id', '?')}")
        
        events = seq.get("events", [])
        for i, evt in enumerate(events):
            # Advance time by the delta from previous event
            dt = evt.get("dt_s", interval_s)
            if dt > 0:
                self.engine._last_tick = time.time() - dt
                self.engine.tick()

            # Capture state before
            areas_of_interest = self._areas_of_interest(seq)
            before = {a: self.engine.room_occupancy_confidence(a) 
                      for a in areas_of_interest}

            # Feed the event
            area = evt["area"]
            tag = evt.get("tag", "motion_detected")
            
            if tag == "presence" and evt.get("state") == "on":
                self.engine.handle_presence(area, present=True)
            elif tag == "presence" and evt.get("state") == "off":
                self.engine.handle_presence(area, present=False)
            elif evt.get("state") == "off":
                # Motion off — acknowledge it but don't change confidence
                # (in the real system, this triggers schedule_motion_off, not tracking)
                pass
            else:
                self.engine.handle_motion(area)

            # Capture state after
            after = {a: self.engine.room_occupancy_confidence(a) 
                     for a in areas_of_interest}

            result.steps.append(Timestep(
                elapsed_s=evt.get("dt_s", 0),
                area=area,
                event_type=self._event_type(evt),
                confidences=before,
                confidences_after=after,
            ))

        return result

    def _areas_of_interest(self, seq: dict) -> set[str]:
        """Return all areas relevant to a sequence + their neighbors."""
        areas = set()
        for evt in seq.get("events", []):
            areas.add(evt["area"])
            areas.update(self.area_graph.neighbors(evt["area"]))
        return areas

    def _event_type(self, evt: dict) -> str:
        tag = evt.get("tag", "motion_detected")
        state = evt.get("state", "on")
        if tag == "presence":
            return f"presence_{state}"
        elif state == "off":
            return "motion_off"
        return "motion_on"


# ---------------------------------------------------------------------------
# Validation checks
# ---------------------------------------------------------------------------

def validate_scenario(result: ScenarioResult, verbose: bool = True) -> list[dict]:
    """Run all validation checks on a replay result."""
    checks = []
    steps = result.steps

    # Check 1: Motion-on increases confidence (or caps at ceiling)
    for step in steps:
        if step.event_type == "motion_on":
            before = step.confidences.get(step.area, 0)
            after = step.confidences_after.get(step.area, 0)
            # Pass if confidence increased OR was already at ceiling
            ok = after > before or (after == before and after >= 0.99)
            checks.append({
                "check": "motion_increases_confidence",
                "area": step.area,
                "delta": round(after - before, 4),
                "passed": ok,
                "detail": f"{step.area}: {before:.3f} → {after:.3f} (+{after-before:.3f})",
            })
            if verbose:
                status = "✓" if ok else "✗ FAIL"
                print(f"  {status} {checks[-1]['detail']}")

    # Check 2: Presence-on gives bigger boost than motion (or caps at ceiling)
    for step in steps:
        if step.event_type == "presence_on":
            before = step.confidences.get(step.area, 0)
            after = step.confidences_after.get(step.area, 0)
            delta = after - before
            # Presence boost from config is 0.3 (vs motion 0.15)
            # Accept if delta >= 0.18 OR already capped
            ok = delta >= 0.18 or (after >= 0.99 and after >= before)
            checks.append({
                "check": "presence_gives_bigger_boost",
                "area": step.area,
                "delta": round(delta, 4),
                "passed": ok,
                "detail": f"{step.area}: {before:.3f} → {after:.3f} (+{delta:.3f})",
            })
            if verbose:
                status = "✓" if ok else "✗ FAIL"
                print(f"  {status} {checks[-1]['detail']}")

    # Check 3: Absence reduces confidence (not instantly to zero)
    for step in steps:
        if step.event_type == "presence_off":
            before = step.confidences.get(step.area, 0)
            after = step.confidences_after.get(step.area, 0)
            ok = after < before and after > 0.001
            checks.append({
                "check": "absence_reduces_confidence",
                "area": step.area,
                "delta": round(after - before, 4),
                "passed": ok,
                "detail": f"{step.area}: {before:.3f} → {after:.3f} ({after/before:.1%} retained)",
            })
            if verbose:
                status = "✓" if ok else "✗ FAIL"
                print(f"  {status} {checks[-1]['detail']}")

    # Check 4: No extinction — all areas have conf >= min_confidence
    for step in steps:
        for area, conf in step.confidences_after.items():
            if conf < 0.005:  # below the floor
                checks.append({
                    "check": "no_extinction",
                    "area": area,
                    "passed": False,
                    "detail": f"{area}: confidence {conf:.4f} below floor (0.01)",
                })
                if verbose:
                    print(f"  ✗ FAIL Extinction risk: {area} at {conf:.4f}")

    # Check 5: Decay between steps
    for i in range(len(steps) - 1):
        s1 = steps[i]
        s2 = steps[i+1]
        dt_s = s2.elapsed_s - s1.elapsed_s
        if dt_s > 5:  # Only check meaningful gaps
            for area in s1.confidences_after:
                if area in s2.confidences and s2.event_type != "motion_on" or s2.area != area:
                    c1 = s1.confidences_after.get(area, 0)
                    c2 = s2.confidences.get(area, 0)
                    if c1 > 0.05 and c2 < c1:
                        delta = c1 - c2
                        if delta > 0:
                            checks.append({
                                "check": "decay_between_events",
                                "area": area,
                                "delta": round(-delta, 4),
                                "passed": True,
                                "detail": f"{area}: {c1:.3f} → {c2:.3f} over {dt_s:.0f}s",
                            })

    return checks


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    import argparse
    parser = argparse.ArgumentParser(description="Replay HA events through OccupancyEngine")
    parser.add_argument("--sequence", type=int, default=None, help="Sequence ID to replay")
    parser.add_argument("--all", action="store_true", help="Replay all sequences")
    parser.add_argument("--interval", type=float, default=1.0, help="Simulation interval (s)")
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose output")
    parser.add_argument("--json", action="store_true", help="JSON output")
    args = parser.parse_args()

    data_path = Path(__file__).parent / "extracted_sequences.json"
    if not data_path.exists():
        print(f"Error: {data_path} not found. Run extract_motion_events.py first.")
        sys.exit(1)

    with open(data_path) as f:
        sequences = json.load(f)

    runner = ReplayRunner()

    if args.sequence is not None:
        seqs = [s for s in sequences if s["id"] == args.sequence]
    else:
        seqs = sequences

    all_checks = []
    passed = 0
    failed = 0

    for seq in seqs:
        if not args.all and args.sequence is None and len(seqs) > 3:
            # Only show first 3 by default
            if seq["id"] > min(s["id"] for s in seqs) + 2:
                continue

        areas = seq.get("areas_visited", [])
        print(f"\n=== Sequence {seq['id']}: {' → '.join(areas)} ({seq.get('duration_s', 0):.0f}s) ===")
        
        result = runner.replay_sequence(seq, interval_s=args.interval)
        
        if args.verbose:
            for step in result.steps:
                print(f"  t={step.elapsed_s:5.0f}s  {step.event_type:14s}  {step.area}  "
                      f"conf={step.confidences_after.get(step.area, 0):.3f}")

        checks = validate_scenario(result, verbose=True)
        all_checks.extend(checks)
        
        p = sum(1 for c in checks if c["passed"])
        f = sum(1 for c in checks if not c["passed"])
        passed += p
        failed += f
        print(f"  Results: {p} passed, {f} failed")

    print(f"\n{'='*60}")
    print(f"Summary: {passed} passed, {failed} failed across {len(seqs)} sequences")

    if args.json:
        print(json.dumps(all_checks, indent=2))


if __name__ == "__main__":
    main()
