# PyScript Configuration And Extension Playbooks

## When To Read

- Editing PyScript YAML config files
- Adding or changing rules, drivers, helper functions, trackers, or blind logic
- Updating schema-like configuration that other runtime code depends on

## Critical Rules

- Preserve unknown YAML keys and existing structure.
- Prefer YAML edits for layout or rule changes; reach for Python only when new runtime behavior is actually needed.
- New rules should use `first_state`, `last`, or `average`; do not introduce new uses of legacy `first`.
- Drivers must ignore unsupported keys gracefully rather than crashing.

## Configuration Sources

- `layout.yml`: area hierarchy plus inputs and outputs.
- `devices.yml`: device ids, driver type, filters, and tags.
- `rules.yml`: trigger prefix, tag requirements, helper functions, merge strategy, and optional guards.
- `connections.yml`: directed adjacency graph for presence scoring.
- `sun_config.yml`: location, window geometry, blind ids, and sun-tracking inputs.

## Extension Playbooks

### Add A Device Class

- Add an entry to `devices.yml` with a unique id, type, and filters.
- Ensure a matching driver exists and follows the current driver interface.
- Keep unsupported-key handling non-fatal.
- Lean on `Device.filter_state()` so caching and filtering remain intact.

### Add Or Adjust A Rule

- Define or update the YAML block in `rules.yml`.
- Reference helper functions by name so they resolve via `get_function_by_name`.
- Choose merge strategy intentionally based on precedence needs.
- Add functions or guards only when the rule needs side effects or veto logic.

### Presence Tuning

- Update `connections.yml` to reflect real movement paths.
- Preserve directionality where the graph expects it.
- Use advanced tracking only when overlapping tracks justify the extra complexity.

### Blind And Sun Integration

- `SunTracker` uses `sun_config.yml` geometry and location to compute recommendations.
- `BlindController` enforces minimum time or percentage deltas to avoid chatter.
- Adjust thresholds when blinds oscillate or react too slowly.

## Quality Gate

- Are updates confined to the intended attributes only?
- Are unspecified keys preserved through cached state?
- Do new YAML ids resolve to real areas, devices, or drivers?
- Is the selected merge strategy justified?
- Does the target driver support the keys being set?
- If `_delayed_off()` was touched, is `@task_unique(f"motion_off_{area_name}", kill_me=True)` still present?

## References

- `pyscript/references/architecture.md`
- `pyscript/references/operations-and-verification.md`
