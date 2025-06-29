# Advanced Tracker

This document explains the multi‑person presence tracker implemented in
`modules/advanced_tracker.py`.  It expands on the short overview in the
main README and provides examples of how sensor input drives the algorithm.

## Theory of Operation

The tracker models your home as a graph of connected rooms.  The edges of
this graph are loaded from `connections.yml` using
`load_room_graph_from_yaml()`.  Each person is tracked by a particle
filter (`PersonTracker`) that maintains a set of possible locations.  On
every update each particle randomly moves to a neighbouring room and its
weight is adjusted based on the `SensorModel`.

### Sensor Model

`SensorModel` records motion events and optional presence sensor states for
each room.  Motion sensors behave like real hardware—they trigger once and
then remain "on" for 7 minutes before resetting.  The model decays the
probability of someone still being in the room from `1.0` down to a small
floor value over this cooldown period.  Presence sensors, if available,
override the probability entirely: ``True`` means the room is occupied and
``False`` means it is empty.  A motion event or a ``True`` presence update
resets the cooldown timer.

### Particle Updates

When `PersonTracker.update()` is called, every particle chooses a random
adjacent room and its weight is set to the likelihood returned by
`SensorModel.likelihood_still_present()`.  If the particle lands in the
same room as the most recent sensor event, its weight receives a small
boost so the cloud quickly collapses onto the triggered room.

Particles are then resampled proportionally to their weight.  The room
with the most particles is the current estimate returned by
`PersonTracker.estimate()`.

`MultiPersonTracker` holds a set of `Person` objects, each wrapping a
`PersonTracker` and zero or more `Phone` objects.  Phones report room data
through `process_phone_data()` and can be associated with a person using
`associate_phone()`.  Generic people are created automatically when a new
identifier is seen.  The manager exposes `process_event()` for sensor
triggers and `step()` to progress the trackers when no new events occur.
Enabling debug mode saves a PNG frame for each step so you can visualize
the distribution over time.  Call `dump_state()` to retrieve a JSON summary
of all people and phones.

## Example Walk‑through

Consider the connections shown in `tests/scenarios/simple_connections.yml`:

```yaml
connections:
  - bedroom: hallway
  - hallway: kitchen
```

With a single person and these events:

```yaml
persons:
  - id: p1
    events:
      - time: 0   # motion in the bedroom
        room: bedroom
      - time: 600 # motion in the hallway ten minutes later
        room: hallway
```

1. At `t=0` the tracker starts with all particles in random rooms.  A
   motion event in `bedroom` makes every particle migrate there after the
   resampling step.  The estimated location becomes `bedroom`.
2. Each second the tracker advances via `step()`.  Particles gradually
   spread to neighbouring rooms according to the graph but retain a high
   weight in the bedroom until the sensor probability decays.
3. At `t=600` another event fires in `hallway`.  Particles teleport there
after resampling and the estimate switches to `hallway`.

You can experiment with more complex scenarios in `tests/scenarios/` and
by writing your own YAML files.

## Using the Tracker in Code

`area_tree.py` initialises a `MultiPersonTracker` via `init_from_yaml()`
when the `init` service is called:

```python
tracker_manager = init_from_yaml(
    "./pyscript/connections.yml", debug=True, debug_dir="pyscript/tracker_debug"
)
```

Motion sensors invoke `update_tracker()` which calls
`tracker_manager.process_event("p1", room)` and stores a debug image if
logging is enabled.

Phones can be registered with `add_phone()` and linked to a person via
`associate_phone()`.  When phone location data arrives, call
`process_phone_data(phone_id, room)` to treat it as a sensor event for the
associated person.  The current state of all trackers can be inspected with
`dump_state()` which returns JSON.

To enable or disable visual logging, pass `debug=True` and specify a
`debug_dir` when calling `init_from_yaml()`.  Images are written to that
folder with names like `frame_000001.png`.

## Testing

Install dependencies and run the unit tests with:

```bash
pip install -r requirements.txt
pip install homeassistant
pytest -q
```

The tests in `tests/test_advanced_tracker.py` cover loading graphs,
updating trackers and verifying that debug frames are produced.  They also
execute several scenarios under `tests/scenarios/`.

## Debug Options

`MultiPersonTracker` accepts two optional arguments to help with automated
testing:

- `event_window` – history length in seconds used when drawing paths.
  Older events are discarded.
- `test_name` – when provided alongside `debug=True`, frames are written to
  `os.path.join(debug_dir, "tests", test_name)`.

Every call to `process_event()` appends a string `(timestamp person_id room)` to
`_event_history`.  The last rendered legend lines are available in
`_last_legend_lines` and include entries like:

```
p1: 100%
solid line: estimated path
dashed orange: true path (tests only)
```

These options are primarily exercised by `tests/test_advanced_tracker.py`.

