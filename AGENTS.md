AGENTS.md
1) Project Mental Model

Composite tree. Area nodes contain nested areas and Device leaves; invoking Area.set_state() fans changes down, while Area.get_state() aggregates descendants so supervisors can read a consolidated snapshot.

Strategy merge. EventManager collects base rule state, event payload, and results from state_functions, then feeds that list into combine_states() with a declared strategy (first_state, last, average; first is legacy only) to preserve non-targeted attributes.

Observer dispatcher. Drivers surface sensor and service activity via Device.input_trigger() / create_event(); EventManager.check_event() fans events to rules, which in turn call Area/Device writers—no direct coupling between sensors and actuators.

Caching discipline. Each Device caches the last applied state and filters unsupported keys before calling its driver so incremental updates (e.g., brightness only) never erase other attributes.

Non-destructive contract. All writes must be incremental deltas. The cached device state is the source of truth, and agents must only merge targeted keys. Full replacements are forbidden unless explicitly required.

2) Critical Paths & Services

Event flow. sensor/service signal → create_event (service) or Device.input_trigger → EventManager.check_event (tag + guard evaluation) → scope/state helper functions → combine_states strategy → Area.set_state → Device.set_state → driver set_state/Home Assistant call.

Startup & control services (@service is the pyscript service decorator per [PyScript HACS docs]):

**Init:** Load YAML (layout, rules), construct AreaTree, hydrate EventManager. (OccupancyEngine was permanently removed 2026-05-03 — subprocess pickle construction was unreliable. Motion sensors + buttons are the critical path; all call sites have None guards that degrade gracefully.)

**Reset:** Log warning, clear globals, then re-run init; use for hard reloads.

**Freeze_area(area_name, recursive=True):** Mark an area (and optionally subtree) frozen so Device.set_state ignores future writes.

**Unfreeze_area(area_name, recursive=True):** Resume updates for a previously frozen area chain.

**Create_event(**kwargs):** Accept service-sourced events (device name, optional tags/state/scope/state functions) and forward them to the event manager.

3) Configuration Sources (illustrative snippets; align with current schema)

layout.yml – define hierarchy, inputs, outputs.

foyer:
  sub_areas:
    - living_room
  inputs:
    motion:
      - sensor_foyer_motion
  outputs:
    - light_foyer_ceiling


devices.yml – map device ids to driver type and tags/filters.

foyer_light:
  type: light
  filters:
    - light
    - hue


rules.yml – declarative automations with tags, scope/state helpers, merge strategy, optional guards.

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


connections.yml – directed adjacency graph for presence scoring.

foyer:
  - living_room
  - hallway
hallway:
  - kitchen


sun_config.yml – location plus per-window geometry/blind ids for sun tracking.

location:
  latitude: 40.0
  longitude: -74.0
max_light_distance: 0.30
areas:
  living_room_window:
    bearing: 135
    window_height: 1.2
    device: living_room_blind


Schema note. Preserve unknown keys when editing YAML. Schema may evolve; forward-compatibility depends on not stripping or renaming unrecognized fields.

4) Invariants & Safety Rails (DO & DON'T)

DO preserve cached attributes—always merge deltas so lights keep prior brightness/color unless explicitly changed.

DO prefer YAML edits for layout/rule tweaks; reach for Python only when adding new helper functions or drivers.

DO use freeze_area before calibration, long tests, or blind re-indexing; unfreeze afterwards.

DON'T emit full-state payloads unless required; incremental updates avoid clobbering cached hue/ct/volume.

DON'T bypass Device.filter_state() or driver filter_state; respect mutual exclusivity (e.g., color_temp vs rgb_color).

DON'T propagate the legacy first strategy in new rules; prefer first_state.

5) Extending Behavior (Playbooks)

Add a new device class.

Append entry to devices.yml (unique id, type, filters).

Ensure a matching driver exists (Device pulls type to select driver). If absent, add driver class inside area_tree.py or modules (follow existing interface: set_state, filter_state, optional input_trigger).

Drivers must ignore unsupported keys gracefully (drop and log), never crash.

Lean on Device.filter_state() so caching and unsupported-key stripping remain intact.

Add or adjust a rule.

Define YAML block in rules.yml with trigger_prefix, tag requirements, scope/state helper names, and combination_strategy.

Reference helper functions by name; they must be importable via get_function_by_name (globals or module attributes).

Pick strategy: first_state (keep earliest generated state when fallbacks should win), last (prefer most recent builder), average (blend numeric values).
first exists only as legacy alias—do not use in new rules.

Add functions guard entries for boolean veto/side-effect helpers (update_tracker, set_cached_last_set_state).

**Presence tuning (OccupancyEngine removed 2026-05-03).**

The `OccupancyEngine` (`modules/occupancy_engine.py`) was permanently removed — subprocess pickle construction was unreliable. `get_occupancy_engine()` now returns `None` unconditionally; all call sites have `None` guards that degrade gracefully. `check_adjacent_motion()` returns `True` when engine is `None` (allows motion-off through). `update_tracker()` delegates to adaptive learner only.

`connections.yml` is inert — it was only consumed by the OccupancyEngine for path scoring. It may be removed in a future cleanup pass.

Motion sensors and buttons are the critical path. Motion-off logic now uses a generation counter (see `_delayed_motion_off` in `area_tree.py`) with four-layer guards: stale generation check, IAS zone re-check, recent-motion window, and sensor-mode kill switch.

6) Debugging & Observability

Successful rule log sequence: debug entry for incoming event → tag/guard pass → scope list resolved (names logged) → combined state printed → logger.info("apply-state", ...) record.

Structured logging. Prefer JSON logs with keys event_id, area, device, state_delta. Preserve these when extending code.

Common failure modes:

No rule matched trigger prefix or tags (watch for debug warning Device ... not found or Required tag messages).

Guard function returned False; rule stops before state apply.

Driver filter_state dropped unsupported keys (check debug about filtered state).

Merge produced no-op because delta under driver threshold (e.g., blind controller uses minimum delta to avoid chatter).

Quick health checks:

Confirm rule-referenced device ids exist via AreaTree.get_device or YAML lookup.

Verify area membership/path with AreaTree.get_area and connections.yml neighbors.

Inspect freeze flags on areas if updates seem ignored (frozen areas log warnings on set attempts).

7) Blind & Sun Integration (Operational)

SunTracker pipeline: Use sun_config.yml latitude/longitude plus Astral to compute solar azimuth/elevation; compare window bearing to determine facing-sun windows; compute closure percentage needed to keep the projected light patch below max_light_distance.

BlindController duties: Pulls recommendations from SunTracker, enforces minimum time/percent deltas before issuing Home Assistant cover commands, and converts between physical height and closed_percent based on BLIND_HEIGHTS or per-device config. Adjust delta thresholds when blinds oscillate or react too slowly.

8) Glossary

Area – Composite node representing a room/zone with child areas/devices and freeze state.

Device – Leaf wrapper holding cached state, driver binding, and helper methods for inputs/outputs.

Driver – Hardware-specific adapter implementing set_state and filter_state to talk to Home Assistant entities.

EventManager – Rule engine that filters events, resolves scope, merges state fragments, and applies results.

Scope Function – Helper returning target Area list for a rule (e.g., local area, neighbors).

State Function – Helper returning state dict fragments merged via strategy.

Merge Strategy – Choice passed to combine_states() that dictates precedence when combining multiple state fragments.

~~**OccupancyEngine** — (Removed 2026-05-03.) Per-room anonymous occupancy tracker. Subprocess pickle construction was unreliable. `get_occupancy_engine()` now returns `None`. Source lives in `modules/occupancy_engine.py` for reference only.~~

~~**AreaGraph** — Standalone dict-based room adjacency graph. No networkx dependency. Was used by OccupancyEngine; now only referenced in tests. Source lives in `modules/area_graph.py`.~~

~~**OccupancyConfig** — Per-room profile dataclass loaded from `occupancy_config.yml`. Removed alongside OccupancyEngine. Source lives in `modules/occupancy_config.py` for reference only.~~

~~**TrackManager** — Legacy tracker. (Removed 2026-05-03 alongside OccupancyEngine shadow-mode validation.)~~

GraphManager – Connection-graph utility powering presence path scoring and visualization. (Inactive — no longer wired into production path.)

SunTracker – Solar model computing which blinds should move and by how much.

BlindController – Wrapper coordinating blind drivers with SunTracker, enforcing throttling.

9) Quality Gate (for agents before making changes)

 Does the rule or service change confine updates to the intended attributes only?

 Are unspecified keys left to cached device state (no unintended resets)?

 Is the chosen combination_strategy justified for the new rule?

 Do all new YAML ids resolve to existing areas/devices or drivers?

 Did a dry-run YAML parse succeed with no schema errors?

 Did the rule evaluate in EventManager.check_event() without exceptions?

 Will freeze_area / unfreeze_area be used during invasive or noisy testing?

 Does the target driver support the keys being set (respecting ct vs rgb exclusivity and other filters)?

10) Post-Implementation: Update Obsidian Documentation

After any pyscript change is implemented and validated, update the matching Obsidian notes via MCP (obsidian_patch_note for surgical edits). This keeps architecture docs in sync and is a quick 2-4 patch operation, not a full rewrite. Only touch notes relevant to your change.

Target notes and when to update each:
- _context.md (Areas/Home/Homeassistant/_context.md) — if new concepts, services, or config keys were added
- Per-class docs (Areas/Home/Homeassistant/Automation/Documentation/<ClassName>.md) — if class interface or behavior changed
- Core Engine (Areas/Home/Homeassistant/Automation/Homeassistant + pyscript automation/Implementation/Core Engine (area_tree.py).md) — if services, class summaries, or config loading changed
- Drivers and Device State Model (same Implementation/ folder) — if driver behavior or guardrails changed
- Configuration Reference (Operations/ folder) — if YAML schema for any config file changed
- Services, Testing, and Diagnostics (Operations/ folder) — if services, startup behavior, or runbook changed
