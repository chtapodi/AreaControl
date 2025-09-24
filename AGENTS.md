# AGENTS.md

## 1) Project Mental Model
- **Composite tree.** `Area` nodes contain nested areas and `Device` leaves; invoking `Area.set_state()` fans changes down, while `Area.get_state()` aggregates descendants so supervisors can read a consolidated snapshot.
- **Strategy merge.** `EventManager` collects base rule state, event payload, and results from `state_functions`, then feeds that list into `combine_states()` with a declared strategy (`first_state`, `first`, `last`, `average`) to preserve non-targeted attributes.
- **Observer dispatcher.** Drivers surface sensor and service activity via `Device.input_trigger()` / `create_event()`; `EventManager.check_event()` fans events to rules, which in turn call `Area`/`Device` writers—no direct coupling between sensors and actuators.
- **Caching discipline.** Each `Device` caches the last applied state and filters unsupported keys before calling its driver so incremental updates (e.g., brightness only) never erase other attributes.

## 2) Critical Paths & Services
- **Event flow.** sensor/service signal → `create_event` (service) or `Device.input_trigger` → `EventManager.check_event` (tag + guard evaluation) → scope/state helper functions → `combine_states` strategy → `Area.set_state` → `Device.set_state` → driver `set_state`/Home Assistant call.
- **Startup & control services** (`@service` is the pyscript service decorator per [PyScript HACS docs]):
  - `init`: Load YAML (`layout`, `rules`), construct `AreaTree`, hydrate `EventManager`, instantiate `TrackManager`.
  - `reset`: Log warning, clear globals, then re-run `init`; use for hard reloads.
  - `freeze_area(area_name, recursive=True)`: Mark an area (and optionally subtree) frozen so `Device.set_state` ignores future writes.
  - `unfreeze_area(area_name, recursive=True)`: Resume updates for a previously frozen area chain.
  - `create_event(**kwargs)`: Accept service-sourced events (device name, optional tags/state/scope/state functions) and forward them to the event manager.

## 3) Configuration Sources (illustrative snippets; align with current schema)
- **`layout.yml`** – define hierarchy, inputs, outputs.
  ```yaml
  # illustrative
  foyer:
    sub_areas:
      - living_room
    inputs:
      motion:
        - sensor_foyer_motion
    outputs:
      - light_foyer_ceiling
  ```
- **`devices.yml`** – map device ids to driver type and tags/filters.
  ```yaml
  # illustrative
  foyer_light:
    type: light
    filters:
      - light
      - hue
  ```
- **`rules.yml`** – declarative automations with tags, scope/state helpers, merge strategy, optional guards.
  ```yaml
  # illustrative
  foyer_motion_on:
    trigger_prefix: "sensor_foyer_motion"
    required_tags: ["on"]
    prohibited_tags: ["manual_override"]
    scope_functions:
      - get_area_local_scope: []
    state_functions:
      - build_warm_light_state: []
    combination_strategy: "last"
    functions:
      - update_tracker: []
  ```
- **`connections.yml`** – directed adjacency graph for presence scoring.
  ```yaml
  # illustrative
  foyer:
    - living_room
    - hallway
  hallway:
    - kitchen
  ```
- **`sun_config.yml`** – location plus per-window geometry/blind ids for sun tracking.
  ```yaml
  # illustrative
  location:
    latitude: 40.0
    longitude: -74.0
  max_light_distance: 0.30
  areas:
    living_room_window:
      bearing: 135
      window_height: 1.2
      device: living_room_blind
  ```

## 4) Invariants & Safety Rails (DO & DON'T)
- **DO** preserve cached attributes—always merge deltas so lights keep prior brightness/color unless explicitly changed.
- **DO** prefer YAML edits for layout/rule tweaks; reach for Python only when adding new helper functions or drivers.
- **DO** use `freeze_area` before calibration, long tests, or blind re-indexing; unfreeze afterwards.
- **DON'T** emit full-state payloads unless required; incremental updates avoid clobbering cached hue/ct/volume.
- **DON'T** bypass `Device.filter_state()` or driver `filter_state`; respect mutual exclusivity (e.g., `color_temp` vs `rgb_color`).

## 5) Extending Behavior (Playbooks)
- **Add a new device class.**
  1. Append entry to `devices.yml` (unique id, `type`, `filters`).
  2. Ensure a matching driver exists (`Device` pulls `type` to select driver). If absent, add driver class inside `area_tree.py` or modules (follow existing interface: `set_state`, `filter_state`, optional `input_trigger`).
  3. Lean on `Device.filter_state()` so caching and unsupported-key stripping remain intact.
- **Add or adjust a rule.**
  1. Define YAML block in `rules.yml` with `trigger_prefix`, tag requirements, scope/state helper names, and `combination_strategy`.
  2. Reference helper functions by name; they must be importable via `get_function_by_name` (globals or module attributes).
  3. Pick strategy: `first_state` (keep earliest generated state when fallbacks should win), `last` (prefer most recent builder), `first` (legacy alias for earliest), `average` (blend numeric values such as dimming or temperature).
  4. Add `functions` guard entries for boolean veto/side-effect helpers (`update_tracker`, `set_cached_last_set_state`).
- **Presence tuning.**
  1. Update `connections.yml` to reflect real walk paths; maintain directionality for path scoring.
  2. Decide between baseline `TrackManager` (list-based, lower overhead) vs `modules/advanced_tracker.py` (particle filter, multi-person). The latter expects richer sensor cadence and optional phone hints—use when tracks overlap frequently.
  3. Validate with tracker tests or logging overlays before deployment.

## 6) Debugging & Observability
- **Successful rule log sequence:** debug entry for incoming event → tag/guard pass → scope list resolved (names logged) → combined state printed → `logger.info("apply-state", ...)` record.
- **Common failure modes:**
  - No rule matched trigger prefix or tags (watch for debug warning `Device ... not found` or `Required tag` messages).
  - Guard function returned `False`; rule stops before state apply.
  - Driver `filter_state` dropped unsupported keys (check debug about filtered state).
  - Merge produced no-op because delta under driver threshold (e.g., blind controller uses minimum delta to avoid chatter).
- **Quick health checks:**
  - Confirm rule-referenced device ids exist via `AreaTree.get_device` or YAML lookup.
  - Verify area membership/path with `AreaTree.get_area` and `connections.yml` neighbors.
  - Inspect freeze flags on areas if updates seem ignored (frozen areas log warnings on set attempts).

## 7) Blind & Sun Integration (Operational)
- **SunTracker pipeline:** Use `sun_config.yml` latitude/longitude plus Astral to compute solar azimuth/elevation; compare window bearing to determine facing-sun windows; compute closure percentage needed to keep the projected light patch below `max_light_distance`.
- **BlindController duties:** Pulls recommendations from `SunTracker`, enforces minimum time/percent deltas before issuing Home Assistant cover commands, and converts between physical height and `closed_percent` based on `BLIND_HEIGHTS` or per-device config. Adjust delta thresholds when blinds oscillate or react too slowly.

## 8) Glossary
- **Area** – Composite node representing a room/zone with child areas/devices and freeze state.
- **Device** – Leaf wrapper holding cached state, driver binding, and helper methods for inputs/outputs.
- **Driver** – Hardware-specific adapter implementing `set_state` and `filter_state` to talk to Home Assistant entities.
- **EventManager** – Rule engine that filters events, resolves scope, merges state fragments, and applies results.
- **Scope Function** – Helper returning target `Area` list for a rule (e.g., local area, neighbors).
- **State Function** – Helper returning state dict fragments merged via strategy.
- **Merge Strategy** – Choice passed to `combine_states()` that dictates precedence when combining multiple state fragments.
- **TrackManager** – Baseline presence tracker merging motion events into tracks based on graph paths.
- **GraphManager** – Connection-graph utility powering presence path scoring and visualization.
- **SunTracker** – Solar model computing which blinds should move and by how much.
- **BlindController** – Wrapper coordinating blind drivers with `SunTracker`, enforcing throttling.

## 9) Quality Gate (for agents before making changes)
- [ ] Does the rule or service change confine updates to the intended attributes only?
- [ ] Are unspecified keys left to cached device state (no unintended resets)?
- [ ] Is the chosen `combination_strategy` justified for the new rule?
- [ ] Do all new YAML ids resolve to existing areas/devices or drivers?
- [ ] Will `freeze_area` / `unfreeze_area` be used during invasive or noisy testing?
- [ ] Does the target driver support the keys being set (respecting ct vs rgb exclusivity and other filters)?
