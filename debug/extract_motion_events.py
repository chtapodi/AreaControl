#!/usr/bin/env python3
"""Extract motion/presence event sequences from HA logs for OccupancyEngine validation.

Reads home-assistant.log and extracts:
1. All motion/presence sensor triggers with timestamps, area, state (on/off)
2. Room-transition sequences (walks) — to validate path tracking
3. Edge cases: rapid events, gaps, presence/absence sequences

Outputs JSON suitable for replay scenario generation.
"""
from __future__ import annotations

import json
import re
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path


# ---------------------------------------------------------------------------
# Patterns
# ---------------------------------------------------------------------------

# Line format:
# TRIGGER: state trigger @binary_sensor.motion_sensor_office_ias_zone == 'on'
#   <EvalFuncVarClassInst ...>( {'tags': ['on', 'motion_detected']} )
# OR (FP2):
# TRIGGER: state trigger @binary_sensor.presence_sensor_living_room == 'on'
#   <EvalFuncVarClassInst ...>( {'tags': ['on', 'presence']} )
TRIGGER_RE = re.compile(
    r"^(?P<timestamp>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{3}) "
    r".*TRIGGER: state trigger @binary_sensor\.(?P<sensor>[\w_]+) "
    r"== '(?P<state>on|off)'.*\{'tags': \['(?P<state2>on|off)', "
    r"'(?P<tag>[\w_]+)'\]"
)


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------

@dataclass
class MotionEvent:
    timestamp: datetime
    sensor: str
    area: str
    state: str       # "on" or "off"
    tag: str         # "motion_detected", "motion_occupancy", "presence"


@dataclass
class EventSequence:
    events: list[MotionEvent] = field(default_factory=list)

    @property
    def duration_s(self) -> float:
        if len(self.events) < 2:
            return 0.0
        return (self.events[-1].timestamp - self.events[0].timestamp).total_seconds()

    @property
    def areas_visited(self) -> list[str]:
        seen: list[str] = []
        for e in self.events:
            if not seen or seen[-1] != e.area:
                seen.append(e.area)
        return seen

    @property
    def on_events(self) -> list[MotionEvent]:
        return [e for e in self.events if e.state == "on"]


# ---------------------------------------------------------------------------
# Sensor → Area mapping
# ---------------------------------------------------------------------------

def parse_area(sensor: str) -> str:
    """Extract area name from sensor id."""
    s = sensor
    for prefix in ("motion_sensor_", "presence_sensor_"):
        if s.startswith(prefix):
            s = s[len(prefix):]
            break
    for suffix in ("_ias_zone", "_iaszone", "_occupancy", "_hue_motion"):
        if s.endswith(suffix):
            s = s[: -len(suffix)]
            break
    return s


# ---------------------------------------------------------------------------
# Sequence grouping
# ---------------------------------------------------------------------------

GAP_THRESHOLD = 60  # seconds


def group_into_sequences(events: list[MotionEvent], gap_s: float = GAP_THRESHOLD) -> list[EventSequence]:
    if not events:
        return []
    sequences: list[EventSequence] = []
    current = EventSequence()
    for evt in events:
        if current.events and (evt.timestamp - current.events[-1].timestamp).total_seconds() > gap_s:
            sequences.append(current)
            current = EventSequence()
        current.events.append(evt)
    if current.events:
        sequences.append(current)
    return sequences


# ---------------------------------------------------------------------------
# Extraction
# ---------------------------------------------------------------------------

def extract_events(log_path: Path) -> list[MotionEvent]:
    events: list[MotionEvent] = []
    with open(log_path) as f:
        for line in f:
            m = TRIGGER_RE.match(line.rstrip("\n"))
            if not m:
                continue
            sensor = m.group("sensor")
            if "motion_sensor" not in sensor and "presence_sensor" not in sensor:
                continue
            ts = datetime.strptime(m.group("timestamp"), "%Y-%m-%d %H:%M:%S.%f")
            area = parse_area(sensor)
            events.append(MotionEvent(
                timestamp=ts,
                sensor=sensor,
                area=area,
                state=m.group("state"),
                tag=m.group("tag"),
            ))
    return events


def analyze(events: list[MotionEvent], sequences: list[EventSequence]) -> dict:
    # Per-area stats
    area_ons: dict[str, int] = defaultdict(int)
    area_offs: dict[str, int] = defaultdict(int)
    for e in events:
        if e.state == "on":
            area_ons[e.area] += 1
        else:
            area_offs[e.area] += 1

    area_stats = {}
    for area in set(area_ons) | set(area_offs):
        area_stats[area] = {"on": area_ons.get(area, 0), "off": area_offs.get(area, 0)}

    # Interesting walks (3+ rooms)
    interesting = []
    for seq in sequences:
        areas = seq.areas_visited
        if len(areas) >= 3:
            interesting.append({
                "areas": areas,
                "duration_s": round(seq.duration_s, 1),
                "on_event_count": len(seq.on_events),
                "start": seq.events[0].timestamp.isoformat(),
            })

    # Rapid transitions (< 1s between different areas)
    rapid = []
    on_events = [e for e in events if e.state == "on"]
    for i in range(len(on_events) - 1):
        delta = (on_events[i+1].timestamp - on_events[i].timestamp).total_seconds()
        if delta < 2.0 and on_events[i].area != on_events[i+1].area:
            rapid.append({
                "from_area": on_events[i].area,
                "to_area": on_events[i+1].area,
                "delta_ms": round(delta * 1000, 1),
                "time": on_events[i].timestamp.isoformat(),
            })

    # Idle periods (5+ min gap)
    idle_periods = []
    for i in range(len(events) - 1):
        delta = (events[i+1].timestamp - events[i].timestamp).total_seconds()
        if delta > 300:
            idle_periods.append({
                "start": events[i].timestamp.isoformat(),
                "end": events[i+1].timestamp.isoformat(),
                "duration_s": round(delta, 1),
                "last_area": events[i].area,
            })

    # Tag breakdown
    tag_counts: dict[str, int] = defaultdict(int)
    for e in events:
        tag_counts[e.tag] += 1

    return {
        "total_events": len(events),
        "total_sequences": len(sequences),
        "time_span": {
            "first": events[0].timestamp.isoformat() if events else None,
            "last": events[-1].timestamp.isoformat() if events else None,
        },
        "area_stats": dict(sorted(area_stats.items(), key=lambda x: -(x[1]["on"]))),
        "tag_breakdown": dict(tag_counts),
        "interesting_walks": interesting[:15],
        "rapid_transitions": rapid[:15],
        "idle_periods": idle_periods[:15],
    }


def main():
    logs = sys.argv[1:] if len(sys.argv) > 1 else ["/home/mango/docker/homeassistant/home-assistant.log"]

    all_events = []
    for log_path in logs:
        all_events.extend(extract_events(Path(log_path)))

    all_events.sort(key=lambda e: e.timestamp)
    sequences = group_into_sequences(all_events)
    summary = analyze(all_events, sequences)

    print(json.dumps(summary, indent=2))

    # Export sequences for scenario generation
    seq_data = []
    for i, seq in enumerate(sequences):
        on_only = seq.on_events
        if len(on_only) < 2:
            continue
        areas = list(dict.fromkeys(e.area for e in on_only))  # deduplicated order
        if len(areas) < 2:
            continue
        seq_data.append({
            "id": i,
            "areas_visited": areas,
            "duration_s": round(seq.duration_s, 1),
            "events": [
                {"area": e.area, "state": e.state, "tag": e.tag,
                 "dt_s": (e.timestamp - seq.events[0].timestamp).total_seconds()}
                for e in on_only
            ],
        })

    out_path = Path(__file__).parent / "extracted_sequences.json"
    with open(out_path, "w") as f:
        json.dump(seq_data, f, indent=2)
    print(f"\nWrote {len(seq_data)} sequences to {out_path}")


if __name__ == "__main__":
    main()
