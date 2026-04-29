# PyScript Architecture And Mental Model

## When To Read

- Working in `area_tree.py` or related runtime modules
- Changing event flow, merge behavior, device writes, trackers, or driver dispatch
- Needing context on how sensor input becomes output state

## Critical Rules

- All writes must be incremental deltas. Full replacements are forbidden unless explicitly required.
- The cached device state is the source of truth for preserving unspecified attributes.
- Do not bypass device or driver filtering when applying state.
- Do not introduce changes that couple sensors directly to actuators outside the event manager flow.

## Mental Model

- Composite tree: `Area` nodes contain nested areas and `Device` leaves. `Area.set_state()` fans updates down, while `Area.get_state()` aggregates descendants.
- Strategy merge: `EventManager` gathers base rule state, event payload, and `state_functions`, then combines them with the declared merge strategy.
- Observer dispatcher: drivers surface activity through `Device.input_trigger()` or `create_event()`, then `EventManager.check_event()` fans events to rules.
- Caching discipline: each `Device` caches the last applied state so incremental updates do not erase unrelated attributes.

## Critical Paths And Services

- Event flow: sensor or service signal -> `create_event` or `Device.input_trigger` -> `EventManager.check_event` -> scope and state helpers -> `combine_states` -> `Area.set_state` -> `Device.set_state` -> driver `set_state` or Home Assistant call.
- `init`: user-defined `@service` in `area_tree.py` that builds the runtime. Never use it as a reload mechanism.
- `reset`: user-defined `@service` that currently calls `pyscript.reload()`. Do not depend on it as the reload entrypoint.
- `freeze_area(area_name, recursive=True)`: blocks future writes for an area or subtree.
- `unfreeze_area(area_name, recursive=True)`: resumes writes.
- `create_event(**kwargs)`: forwards service-sourced events into the event manager.

## Implementation Guidance

- Preserve non-targeted attributes when building state.
- Prefer `first_state`, `last`, or `average` intentionally; `first` is legacy only.
- Respect mutual exclusivity in driver filters such as `color_temp` vs `rgb_color`.
- Use `freeze_area` during invasive calibration or noisy operational tests.

## Glossary

- Area: composite room or zone node with child areas or devices and freeze state.
- Device: leaf wrapper with cached state, driver binding, and input or output helpers.
- Driver: hardware adapter implementing `set_state` and `filter_state`.
- EventManager: rule engine that filters events, resolves scope, merges state, and applies results.
- Scope Function: helper returning target areas for a rule.
- State Function: helper returning state fragments merged by strategy.
- TrackManager: baseline presence tracker.
- GraphManager: connection graph utility for path scoring and visualization.
- SunTracker: solar model for blind behavior.
- BlindController: blind coordination wrapper that enforces throttling.

## References

- `pyscript/references/config-and-extension.md`
- `pyscript/references/operations-and-verification.md`
