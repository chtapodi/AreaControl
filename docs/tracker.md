# Advanced Tracker Guide

This document details the particle-filter based tracker implemented in
`modules/advanced_tracker.py`. The tracker models each person as a
collection of particles moving through the house layout. Motion sensor
triggers update particle weights so that the distribution gradually
converges on the person's location.

## Overview

The tracker loads the allowed transitions between areas from
`connections.yml` using `load_room_graph_from_yaml`. Each detected person
is represented by a `PersonTracker` holding many `Particle` objects. A
`MultiPersonTracker` manages these trackers and steps them forward.

```
flowchart LR
    A[Motion sensor fires] --> B[update_tracker]
    B --> C[MultiPersonTracker.process_event]
    C --> D[PersonTracker.update]
    D --> E[move particles]
    D --> F[weight by SensorModel]
    F --> G[resample]
    G --> H[estimate current room]
```

`update_tracker` in `area_tree.py` calls `process_event("p1", room)` for
now, always tracking a single virtual person.

## Core classes

- **RoomGraph** – bidirectional graph of connected rooms.
- **SensorModel** – provides a likelihood that a person remains in a room
  after a sensor fired there. It decays over time with a cooldown period.
- **Particle** – lightweight object storing a candidate room.
- **PersonTracker** – maintains a set of particles for one person and
  updates them on each step.
- **MultiPersonTracker** – orchestrates multiple `PersonTracker`
  instances and handles optional visualization.

### Event flow

When `update_tracker` is called with a motion event:

```python
tracker_manager.process_event("p1", room_id)
```

Internally `PersonTracker.update` will:

1. Record the sensor trigger via `SensorModel.record_trigger`.
2. Move every particle to a random neighbouring room.
3. Weight each particle using `SensorModel.likelihood_still_present`.
4. Resample to keep the particle count constant.

Calling `step()` without a sensor reading also advances the trackers,
allowing the distribution to diffuse over time.

## Example sequence

Assume the graph connects `hallway` to both `bedroom` and `kitchen`.

1. `hallway` sensor fires.
   ```python
   tracker.process_event("p1", "hallway")
   ```
   Most particles collapse into `hallway`.
2. Seconds later the kitchen sensor fires.
   ```python
   tracker.process_event("p1", "kitchen")
   ```
   The particles shift toward `kitchen` and nearby rooms.

At any time `estimate_locations()` returns the most likely room per
person:

```python
>>> tracker.estimate_locations()
{"p1": "kitchen"}
```

## Testing

Run the unit tests with `pytest`:

```bash
pip install -r requirements.txt
pytest -q
```

The tracker is exercised in `tests/test_advanced_tracker.py` and via
`area_tree.py` integration tests.

## Visual logging

`MultiPersonTracker` accepts `debug=True` and a `debug_dir` when created.
Each call to `process_event` or `step` then saves a PNG frame showing the
current particle distribution. Enable this by constructing the tracker
with:

```python
tracker = init_from_yaml("connections.yml", debug=True, debug_dir="tracker_debug")
```

The frames will be written to the specified directory and can be
assembled into a video to visualize movement.
