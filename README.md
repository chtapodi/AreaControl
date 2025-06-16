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
- [Running with Home Assistant](#running-with-home-assistant)

## Project Layout

```
area_tree.py          # Core classes and services
modules/tracker.py    # Presence tracking utilities
layout.yml            # Area hierarchy definition
devices.yml           # Device types and tags
connections.yml       # Allowed area transitions for tracking
rules.yml             # Automation rules
requirements.txt      # Python dependencies
```

The two main Python files are [`area_tree.py`](area_tree.py) and [`modules/tracker.py`](modules/tracker.py).

## YAML Configuration

The repository relies on several YAML files:

- [`layout.yml`](layout.yml) defines the tree of areas, the devices inside each area, and their relationships.
- [`devices.yml`](devices.yml) lists device definitions and filters.
- [`connections.yml`](connections.yml) describes which areas are considered connected for presence tracking.
- [`rules.yml`](rules.yml) holds automation rules that pair events with actions.

These files are loaded at startup and are referenced throughout the code.

## Areas and Devices

[`area_tree.py`](area_tree.py) builds the hierarchy of `Area` objects and wraps hardware in `Device` objects. The [`AreaTree` class](area_tree.py) exposes helpers to query or modify the tree. Each device tracks a cached state and forwards updates to its underlying driver.

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

## Event and Rule Workflow

Automation behavior is driven by the rules in [`rules.yml`](rules.yml). When a device triggers an event—via a sensor callback or a service call—the [`EventManager`](area_tree.py) evaluates matching rules and applies the resulting state to the appropriate areas:

1. **Matching rules.** The manager checks each rule's `trigger_prefix` and optional tags.
2. **Determining scope.** Scope functions (listed under `scope_functions` in the rule) resolve which areas should receive the new state.
3. **Building state.** State functions return extra state fragments which are combined with any manual state supplied in the event and the default `state` block of the rule.
4. **Running arbitrary functions.** Rules may contain additional functions that can veto or modify behavior.
5. **Applying state.** After combining all states, the manager calls `set_state` on each area in the scope, which in turn updates child devices.

See the [`execute_rule`](area_tree.py) method for the full logic.

## Presence Tracking

[`modules/tracker.py`](modules/tracker.py) maintains a history of movement between areas using a connection graph from [`connections.yml`](connections.yml). The `TrackManager` collects events, merges tracks, and can visualize the graph of recent locations. Functions such as `update_tracker` in [`area_tree.py`](area_tree.py) feed sensor events into the tracker.

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

## Running with Home Assistant

Install dependencies with:

```bash
pip install -r requirements.txt
```

Copy the YAML files and Python modules into your Home Assistant `pyscript` directory. After reloading Pyscript, call the `init` service to build the area tree and start processing events. Services like `create_event` can be used to simulate button presses or other triggers.

Refer back to [Event and Rule Workflow](#event-and-rule-workflow) to understand how a service call becomes an action inside an area.

