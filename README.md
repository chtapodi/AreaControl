# Area Control

Area Control is a collection of [pyscript](https://github.com/custom-components/pyscript) scripts for Home Assistant. It organizes lights and sensors into an area hierarchy and reacts to events based on YAML-configured rules.

- **Python modules** implement the area tree, devices, event processing and presence tracking.
- **YAML files** describe the layout of the house and automation rules.

This README outlines the main pieces of the project and how events flow through the system.

## Table of Contents
- [Project Layout](#project-layout)
- [YAML Configuration](#yaml-configuration)
- [Areas and Devices](#areas-and-devices)
- [Major Classes](#major-classes)
- [Event and Rule Workflow](#event-and-rule-workflow)
- [Presence Tracking](#presence-tracking)
- [Rule Examples](#rule-examples)
- [Design Philosophy](#design-philosophy)
- [Running with Home Assistant](#running-with-home-assistant)

## Project Layout

```
area_tree.py          # Core classes and services
modules/tracker.py    # Presence tracking utilities
modules/sun_tracker.py # Sun position utilities
modules/blind_controller.py # Smart blind control helpers
layout.yml            # Area hierarchy definition
devices.yml           # Device types and tags
connections.yml       # Allowed area transitions for tracking
rules.yml             # Automation rules
requirements.txt      # Python dependencies
```

The two main Python files are [`area_tree.py`](area_tree.py) and [`modules/tracker.py`](modules/tracker.py).

## YAML Configuration

### Config Paths

All file locations live in [`config.yml`](config.yml) under `paths`. If the file
is missing, defaults are used. `init()` in [`area_tree.py`](area_tree.py) calls
`load_config()` and passes the resolved paths to each manager.

```yaml
paths:
  layout: "./pyscript/layout.yml"
  rules: "./pyscript/rules.yml"
  devices: "devices.yml"
  connections: "./pyscript/connections.yml"
  sun: "./pyscript/sun_config.yml"
```

### layout.yml
- Loader: `AreaTree(...)` in `init()`; parsed in `_create_area_tree`.
- Use: Builds the area hierarchy; spawns devices for `outputs`; registers sensor
  callbacks for `inputs`.
- Fill out: each top-level key is an area. `direct_sub_areas` and `sub_areas`
  define children; `outputs` list device ids; `inputs` is a dict of sensor types
  (`motion`, `presence`, `service`) to lists of entity ids. Omit or set `-` when
  unused.

### devices.yml
- Loader: `AreaTree(..., devices_file=...)`.
- Use: Overrides driver selection and per-device options (e.g., blind height).
- Fill out: per device id, set `type` (light, blind, speaker, plug,
  contact_sensor, fan, television), `filters` (e.g., `hue` vs `kauf`), optional
  `height` for blinds (meters). Missing entries fall back to name heuristics.

**NOTE:** A device must be present in both `devices.yml` and `layout.yml` for it to be recognized by the code.
**NOTE:** Zigbee lights have ids at the light level and at the device(?) level

### rules.yml
- Loader: `EventManager(...)`; read in `execute_rule()`.
- Use: Defines trigger prefixes, scopes, state builders, and guards.
- Fill out: `trigger_prefix`; optional `required_tags`/`prohibited_tags`;
  `scope_functions` and `state_functions` as lists of `{function_name: [args]}`;
  `state` as a partial state dict; `combination_strategy`; `functions` for guard/side-effect helpers.

**Combination Strategies:**
- `first_state` - Uses the first valid (non-empty) state in the list order (recommended for most rules)
- `last` - The last non-empty state wins
- `average` - Numeric values averaged, dicts merged recursively
- `first` - Legacy alias for `first_state` (prefer explicit `first_state`)

### connections.yml
- Loader: `TrackManager(connections_config=...)` → `GraphManager` in
  `modules/tracker.py`.
- Use: Presence path scoring, track association, and graph visualization.
- Fill out: under `connections`, add list items like `{kitchen: hallway}` to add
  undirected edges between areas being tracked.

### sun_config.yml
- Loader: `SunTracker` in `modules/sun_tracker.py`; optional pairing via
  `BlindController`.
- Use: Location/geometry for sun-facing detection and blind closure math.
- Fill out: `location.latitude`/`longitude`; `max_light_distance` (meters) for
  allowed sunlight patch; under `areas`, provide `bearing` (degrees),
  `window_height` (meters), optional per-window `max_light_distance`, optional
  `device` id for the associated blind.

These files load at startup and power the code paths above.

## Areas and Devices

[`area_tree.py`](area_tree.py) builds the hierarchy of `Area` objects and wraps hardware in `Device` objects. The [`AreaTree` class](area_tree.py) exposes helpers to query or modify the tree. Each device tracks a cached state and forwards updates to its underlying driver.

Outputs whose names contain `blind` are automatically treated as smart blinds.
They can be controlled by specifying a `closed_percent` or providing a physical
`height` value, which is translated into the correct percentage using the blind
height configured in `area_tree.py`.

Service functions such as `init()` and `reset()` (see the top of [`area_tree.py`](area_tree.py)) create global managers for the tree, event handling and the tracker.

## Major Classes

Below is a quick reference for the most frequently used classes. Dive into
[`area_tree.py`](area_tree.py) and [`modules/tracker.py`](modules/tracker.py) for
the full implementations.

- **`Area`** – Represents a logical area or room. Areas can contain other areas
  and `Device` objects. Calling `set_state()` on an area propagates the state to
  all of its children. Methods such as `get_children()` and `get_state()` help
  inspect or update the hierarchy.
- **`Device`** – Wraps a driver object provided by Home Assistant. Each device
  caches its last state and exposes `set_state()` and `input_trigger()` to apply
  updates or generate events.
- **`AreaTree`** – Loads the YAML layout and provides helpers like
  `get_area(name)` or `get_device(name)` to navigate the structure. It also keeps
  track of the root area.
- **`EventManager`** – Reads `rules.yml`, watches for events, and executes rules
  using `execute_rule()`. It handles scope resolution, state combination and
  running any additional functions defined by a rule.
- **`TrackManager`, `Track` and `Event`** – Found in
  [`modules/tracker.py`](modules/tracker.py). These classes maintain a sequence
  of presence events and can merge tracks or visualize area transitions.
- **`SunTracker`** – See [`modules/sun_tracker.py`](modules/sun_tracker.py) for
  calculating the sun's position and determining whether an area faces the sun.
  The class also provides `recommended_blind_closure()` to compute how far to
  close smart blinds so that direct light does not extend past a configurable
  distance onto the floor.
- **`BlindController`** – Provided in
  [`modules/blind_controller.py`](modules/blind_controller.py) for integrating
  `SunTracker` with blind devices. It uses `BlindDriver` to set positions while
  avoiding frequent or tiny adjustments.
- **`BlindDriver`** – Handles smart blinds that accept either a percentage
  closed or a physical height. Heights are converted to percentages using the
  configured blind height.
- **`SpeakerDriver`** – Controls media speakers like Google Home. Tracks volume
  and what is currently playing, and allows adjusting volume via `set_state()`.
- **`PlugDriver`** – Operates smart plugs or switches to turn devices on or off
  and can report power usage if a sensor is available.
- **`ContactSensorDriver`** – Wraps door or window sensors providing open/closed
  events.
- **`FanDriver`** – Extends `PlugDriver` for fans and can store which window it
  is associated with.
- **`TelevisionDriver`** – Controls televisions through a `media_player` entity
  and reports the currently playing media.
- **`HueLight`** – Light driver for Philips Hue bulbs. Uses color calibration so
  lights with different hardware show consistent colors.
- **`KaufLight`** – Light driver for Kauf bulbs with RGB-to-color_temp mapping.
- **`MotionSensorDriver`** – Handles motion sensor inputs, generates on/off events.
- **`PresenceSensorDriver`** – Handles presence sensor inputs (more nuanced than motion).
- **`ServiceDriver`** – Handles service input triggers (buttons, service calls).

## Event and Rule Workflow

Automation behavior is driven by the rules in [`rules.yml`](rules.yml). When a device triggers an event—via a sensor callback or a service call—the [`EventManager`](area_tree.py) evaluates matching rules and applies the resulting state to the appropriate areas:

1. **Matching rules.** The manager checks each rule's `trigger_prefix` and optional tags.
2. **Determining scope.** Scope functions (listed under `scope_functions` in the rule) resolve which areas should receive the new state.
3. **Building state.** State functions return extra state fragments which are combined with any manual state supplied in the event and the default `state` block of the rule.
4. **Running arbitrary functions.** Rules may contain additional functions that can veto or modify behavior.
5. **Applying state.** After combining all states, the manager calls `set_state` on each area in the scope, which in turn updates child devices.

See the [`execute_rule`](area_tree.py) method for the full logic.

### Available Scope Functions

- **`get_area_local_scope`** - Get the specific area associated with the device
- **`get_local_scope`** - Get the immediate area containing the device
- **`get_immediate_scope`** - Alias for get_local_scope
- **`get_entire_scope`** - Get all areas in the house (global control)

### Available State Functions

- **`get_time_based_state`** - Returns brightness/color based on time of day
- **`toggle_state`** - Toggles on/off state
- **`toggle_status`** - Toggles status (0/1)
- **`get_last_set_state`** - Returns the last manually set state
- **`get_last_track_state`** - Returns state based on presence tracking

### Available Guard Functions

- **`update_tracker`** - Update presence tracker with the event
- **`motion_sensor_mode`** - Apply motion sensor rules
- **`set_cached_last_set_state`** - Cache the current state as "manually set"

## Presence Tracking


[`modules/advanced_tracker.py`](modules/advanced_tracker.py) implements a
particle-filter based tracker. It follows people through the area graph defined
in [`connections.yml`](connections.yml) and can output visualization frames. The
`update_tracker` function in [`area_tree.py`](area_tree.py) feeds motion sensor
events into the tracker and logs each generated frame.
For a thorough explanation of the algorithm and code walkthroughs, see
[the detailed tracker README](modules/ADVANCED_TRACKER_README.md).

When more than one track is close enough to merge with a new event, the manager
looks at each candidate's last step. It compares the expected next hop along the
shortest path and the estimated speed between the previous two events. The track
whose direction and velocity best match the new observation is selected.

## Rule Examples

Rules live in [`rules.yml`](rules.yml). Each rule links a trigger prefix to a
set of scope and state functions. A simplified example:

```yaml
toggle_light_color:
  trigger_prefix: "service_input_button_double"
  scope_functions:
    - get_area_local_scope: []
  state_functions:
    - toggle_state: []
  state: {}
```

When a device beginning with `service_input_button_double` fires an event, the
scope is determined by `get_area_local_scope`. The resulting state from
`toggle_state` is merged with the empty base `state` block.

States are simple dictionaries. For instance, a light-on state might be:

```yaml
state:
  status: 1
  brightness: 255
```

State functions can return partial states which are combined using strategies
like `first_state` or `merge_state`.

## Design Philosophy

The rule engine aims to make automation **incremental** and **non-destructive**.
States are merged rather than overwritten so that each rule only adjusts the
properties it cares about. For example, a rule that only changes `rgb_color`
does not toggle the light on or off unless `status` is explicitly provided.

Key principles:

* **Partial state updates.** Rules may specify just one or two keys. Any
  attribute not present in the final state retains its previous value thanks to
  device caching.
* **Color does not imply power.** Changing `rgb_color` or `color_temp` merely
  updates the color; it does not affect the `status` flag. This prevents color
  adjustments from accidentally turning lights on or off.
* **Color calibration.** Light drivers can apply per-device calibration
  profiles so that the same RGB values appear consistent across different
  hardware.
* **Function-based scopes.** Scope and state logic is delegated to functions
  referenced by name, letting complex behavior live in Python while YAML stays
  declarative.
* **Combination strategies.** When multiple state fragments are returned from
  functions, they are merged according to a strategy (e.g., averaging or using
  the first non-null value).
* **Modular events.** Manual state from an incoming event is merged with state
  functions and the rule's default to create a final result. Additional
  functions may veto the rule entirely if conditions are not met.

## Control Services

The following services are available for runtime control:

- **`init`** - Load YAML configs, build AreaTree, instantiate EventManager & TrackManager. Called automatically on startup.
- **`reset`** - Clear all globals and re-run init. Use for hard reloads during development.
- **`create_event(**kwargs)`** - Forward sensor/service events to EventManager. Accepts:
  - `device_name` - Trigger prefix for rule matching
  - `tags` - List of tags (e.g., `["on"]`, `["off"]`)
  - `state` - State dictionary to apply
  - `scope_functions` - List of scope function calls
  - `state_functions` - List of state function calls
- **`freeze_area(area_name, recursive=True)`** - Mark an area frozen so Device.set_state ignores future writes. Useful for calibration or testing.
- **`unfreeze_area(area_name, recursive=True)`** - Resume updates for a previously frozen area.
- **`get_total_average_state(key=None)`** - Get aggregated state from all devices.

## Running with Home Assistant

Install dependencies with:

```bash
pip install -r requirements.txt
```

Copy the YAML files and Python modules into your Home Assistant `pyscript`
directory. Helper modules such as `logger.py` must live under
`<config>/pyscript/modules/` (or enable `allow_all_imports` in Pyscript) so they
can be imported. After copying new modules, reload Pyscript and call the `init`
service to build the area tree and start processing events. Services like
`create_event` can be used to simulate button presses or other triggers. The new
`freeze_area` and `unfreeze_area` services allow you to temporarily lock an area
so lights ignore any events until unfrozen.

Refer back to [Event and Rule Workflow](#event-and-rule-workflow) to understand how a service call becomes an action inside an area.

## Future TODOs

- **Temperature inputs are not fully wired into the rule engine yet.** `layout.yml`
  already declares `temperature` inputs, and `rules.yml` contains
  `temp_rise_above` / `temp_fall_below`, but the current system still needs a
  concrete implementation contract for:
  - where per-area temperature thresholds live
  - what event tags a temperature driver should emit on threshold crossings
  - whether temperature device names should follow the existing `sensor_...`
    rule prefix or whether the rules should be updated to match layout naming
  - how hysteresis/debounce should work to avoid oscillation around thresholds
