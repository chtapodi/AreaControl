# Log Debugging And Behavior Investigation

## When To Read

- A light (or other device) changed state unexpectedly and you need to explain why
- Motion sensors seem unresponsive or trigger the wrong behavior
- Automation logic is suspected of producing incorrect outputs
- Trigger pipeline health needs verification after a PyScript change

## Critical Rules

- All PyScript automation output uses the `[area_tree]` logger.
- The authoritative log file is `home-assistant.log` at the repo root.
- The container is named `homeassistant`. Use `docker logs homeassistant --since=...` for live queries.
- Timestamp is always the first field: `YYYY-MM-DD HH:MM:SS.mmm`.
- Do not assume an automation fired without finding a matching `TRIGGER:` and `EventManager:check_event` line.

## Log Access

### Scripted extraction (preferred for agent analysis)

Use `shell/ha-log-extract.sh` for any investigation involving more than a quick tail. It strips ANSI, excludes noise, caps output, and prints a stats header so agents can gauge volume before committing context.

**New in 2026-04-27:** structured JSON logging with event_id tracing. Every event now carries a unique `event_id` that threads through the full pipeline. Use `--trace <event_id>` to follow a single event, or `--correlate <area>` for an area's compound timeline.

```sh
# Quick stats — how many relevant lines in a window?
shell/ha-log-extract.sh --since 2026-04-08T13:00:00Z --until 2026-04-08T16:00:00Z --category all --stats-only

# Predefined category extract
shell/ha-log-extract.sh --since "1h" --category motion --limit 200
shell/ha-log-extract.sh --since "1h" --category lights --limit 200
shell/ha-log-extract.sh --since "1h" --category errors --limit 100

# Custom debug pattern (intersects with category if both given)
shell/ha-log-extract.sh --since "3h" --pattern "living.room.*rgb.*255.*0.*0" --limit 200
shell/ha-log-extract.sh --since "2h" --category pyscript --pattern "hallway.*motion_off" --limit 200

# Full window, unlimited output (use sparingly — large output)
shell/ha-log-extract.sh --since 2026-04-08T13:00:00Z --until 2026-04-08T16:00:00Z --category motion --limit 0
```

**Available categories:** `motion` | `lights` | `triggers` | `pyscript` | `errors` | `all`

**Stats header format** (always first 3 lines of output):
```
# TOTAL: <raw docker log lines>
# MATCHED: <lines after filtering>
# WINDOW: <since> to <until>
```

**When to use `--pattern` vs `--category`:**
- `--category` — broad class of events; good for initial sweep
- `--pattern` — specific debug question; translate the symptom into a regex targeting area name + key + value
- Combine both to narrow: `--category pyscript --pattern "kitchen"` = pyscript events for kitchen only

### Pattern cookbook for common debug scenarios

| Symptom | Pattern |
|---|---|
| Lights stayed in red/late-night mode | `rgb.*255.*0.*0\|late.night` |
| Light held on by house-quiet guard | `house quiet.*extending hold\|check_house_quiet.*blocking` |
| Living room stuck on manual hold | `living.room.*manual.hold\|manual_hold.*living` |
| Area didn't turn off after motion cleared | `schedule_motion_off.*<area>\|motion_off.*<area>` |
| Presence sensor churn (rapid on/off) | `presence_sensor.*<area>.*(on\|off)` |
| Color transition not happening | `color_temp\|circadian\|sun_tracker` |
| Rule blocked by guard | `failed.*not running\|Fuction.*failed` |
| Device skipped/rejected | `Skipping\|Exception setting state` |
| Task cleanup error (NoneType) | `cleanup_global_state\|NoneType.*done` |

### Raw docker access (for quick tails)

```sh
# Recent logs from the container (last N minutes)
docker logs homeassistant --since="5m" 2>&1 | grep "\[area_tree\]"

# Search the persistent log file at the repo root
grep "\[area_tree\]" home-assistant.log | grep "<pattern>"
```

## Keyword Map

### Rule lifecycle

| Question | Search term |
|---|---|
| Did any trigger fire? | `TRIGGER:` |
| Which rule matched? | `EventManager:check_event()` + device name |
| Which rule executed? | `EventManager:execute_rule()` |
| Was a rule blocked by a guard? | `function failed` or `Fuction '...' failed` |
| What state was merged? | `merged state` or `merged_state:` |
| What was applied? | `apply-state` |
| Was the device type filter the blocker? | `type '...' not in filter` |
| Trace event pipeline | `--trace <event_id>` (ha-log-extract.sh) |

### Motion-off lifecycle

| Question | Search term |
|---|---|
| Off timer started? | `schedule_motion_off: scheduling off` (structured: area, delay_s) |
| Off timer elapsed, lights turned off? | `schedule_motion_off: off applied` (structured: area, action: off_applied) |
| Off timer cancelled by new motion? | `cancel_motion_off` (structured: area, action: cancelled) |
| Off blocked by adjacent area motion? | `check_adjacent_motion: blocking off for` |
| Off skipped — motion mode off? | `schedule_motion_off: sensor mode off` (structured: action: skip_sensor_mode_off) |
| Trace motion-off lifecycle | `--trace motion-off_<area>` (ha-log-extract.sh) |

### Sensor and device health

| Question | Search term |
|---|---|
| Sensor trigger registered? | `generating state trigger` |
| No sensor events appearing? | no `TRIGGER:` lines after a known state change |
| Device write skipped by area? | `Area <name>: Skipping <device>` |
| Device write rejected by driver? | `Exception setting state on child` |
| `use_rgb` key error? | `extra keys not allowed @ data['use_rgb']` |
| Manual override detected? | `Manual override set for` |
| Area frozen (writes blocked)? | `freeze_area` / search for frozen area name |

## Structured Log Schema (New: 2026-04-27)

All automation pipeline logs now use structured JSON via Logger.extra=. The JSON object starts with {"timestamp": ...} and is appended to the human-readable message by the Logger class.

### Common fields in every structured line

- `timestamp` (float) — epoch seconds
- `message` (string) — human-readable description
- `event_id` (string) — unique per-event identifier

### Pipeline stage fields

| Log Site | Extra Fields | Purpose |
|----------|-------------|---------|
| `EventManager:check_event()` | `event`, `matches` | Trigger event + matched rule names |
| `EventManager:execute_rule()` | `rule`, `device`, `event_data` | Active rule context |
| `scope resolved` | `scope` (list of area names) | Target areas |
| `function state` | `function`, `result` | Per-helper state fragment |
| `merged state` | `final_state`, `strategy` | Combined state pre-apply |
| `function failed` | `function`, `action: block_rule` | Guard that blocked the rule |
| `apply-state` | `state`, `scope` | State being applied to scoped areas |
| `schedule_motion_off: scheduling off` | `area`, `delay_s` | Off timer start |
| `schedule_motion_off: off applied` | `area`, `action: off_applied` | Off timer completed |
| `cancel_motion_off` | `area`, `action: cancelled` | Off timer cancelled by new motion |
| `Device.set_state` | `device`, `state` | Device-level state write |
| `Device: applied state` | `device`, `state` | Driver return after set_state |

### How to use for debugging

```sh
# Find an event_id
shell/ha-log-extract.sh --since "10m" --category pyscript --pattern "event_id" --limit 10

# Follow an event through the pipeline (all sites that reference this event_id)
shell/ha-log-extract.sh --since "10m" --trace 18abc123_4f3a

# Motion-off lifecycle uses its own event_id scheme
shell/ha-log-extract.sh --since "30m" --trace motion-off_kitchen

# For structured analysis with jq
shell/ha-log-extract.sh --since "30m" --category pyscript --json | grep "^\[JSON\]" | jq -c '[.event_id, .message, .area // .scope // .device // ""]'
```

## Motion-Off Delay Reference

Configured in `layout.yml` per area. Determines how long after motion stops before lights turn off.

| Area | Delay | Notes |
|---|---|---|
| kitchen | 900s (15 min) | |
| laundry_room | 900s | |
| office | 900s | |
| bathroom | 300s (5 min) | |
| hallway | 120s (2 min) | |
| All other areas | 15 min (default) | `DEFAULT_MOTION_OFF_DELAY` in `area_tree.py` |

## Motion Rules Reference

Two motion-off rules exist in `rules.yml`:

| Rule | Tags | Behavior |
|---|---|---|
| `motion_off_ias` | `['off', 'motion_detected']` | IAS zone sensor — checks adjacent motion, schedules delayed off |
| `motion_off_after_15` | `['off', 'motion_occupancy']` | Occupancy sensor — same path as `motion_off_ias` |
| `motion_on` | `['on', 'motion_detected']` or `['on', 'motion_occupancy']` | Turns lights on, cancels pending off, records on-time |
| `living_room_presence_off` | `['off', 'presence']` | Living room presence sensors use the same delayed-off path |

Both off rules follow the same flow: `motion_sensor_mode` gate -> `check_adjacent_motion` -> `schedule_motion_off` (which starts the timer and returns `False` to block immediate off).

After the timer elapses, `_delayed_off` runs a re-check loop: `motion_sensor_mode` -> lights-already-off check (manual bypass) -> `check_house_quiet` (blocks if no other area has had motion in `quiet_house_window_seconds`) -> `check_adjacent_motion` -> apply off. If the house-quiet guard blocks, it sleeps `quiet_recheck_seconds` and loops. New motion cancels the loop via generation bump.

## Structured Log Trace Recipe (2026-04-27+)

Since the structured logging update, you can follow an event end-to-end:

```sh
# 1. Find recent event_ids
shell/ha-log-extract.sh --since "5m" --category pyscript --pattern "event_id" --limit 10

# 2. Trace a specific event_id through the pipeline
shell/ha-log-extract.sh --since "5m" --trace 18abc123_4f3a

# 3. Correlate all logs for an area
shell/ha-log-extract.sh --since "10m" --correlate kitchen

# 4. JSON analysis
shell/ha-log-extract.sh --since "30m" --category pyscript --json | grep "^\[JSON\]" | jq '{event: .event_id, msg: .message, area: (.area // .scope // "")}'
```

## Ready-To-Run Grep Recipes

### Lights turned off unexpectedly

```sh
grep "schedule_motion_off" home-assistant.log | grep "<area_name>" | tail -10
```

If "off applied" appears: the timer elapsed normally. Check:
- Was there motion between the off event and the timer expiry? Look for `cancel_motion_off` or new `TRIGGER:.*<area>.*== 'on'`.
- Was `check_adjacent_motion` supposed to block it? Search for `check_adjacent_motion: blocking off for <area>`.

### Lights didn't turn on when entering a room

```sh
grep "TRIGGER:" home-assistant.log | grep "<sensor_name>" | tail -5
```

If no lines: the trigger pipeline is broken or the sensor is offline. See `operations-and-verification.md` for recovery steps.

If lines exist but lights didn't change:
```sh
grep "EventManager:check_event" home-assistant.log | grep "<sensor_name>" | tail -5
```
Check whether any rules matched. If `Matches:[]`, no rule was configured for that trigger/tags combination.

### Check what rule matched a specific event

```sh
grep "EventManager:check_event" home-assistant.log | grep "<device_name>" | tail -10
```

The `Matches:[...]` portion lists which rules applied. Cross-reference with `rules.yml`.

### Verify trigger pipeline after reload

```sh
docker logs homeassistant --since="2m" 2>&1 | grep "generating state trigger.*motion"
```

If no output: triggers were not registered. Recover with a full restart (see `operations-and-verification.md`).

### Find all ERROR lines from today

```sh
grep "$(date +%Y-%m-%d).*ERROR" home-assistant.log | grep "\[area_tree\]"
```

## Documenting Findings

Use the Obsidian MCP server ("the documentation", "the vault") to capture debugging findings and runbooks. See `.opencode/references/obsidian-vault.md` for terminology and MCP tool usage. Prefer surgical edits (`obsidian_patch_note`) when updating an existing note.

## References

- `pyscript/references/operations-and-verification.md` — trigger pipeline health and reload recovery
- `pyscript/references/architecture.md` — event flow mental model and critical paths
- `pyscript/references/config-and-extension.md` — `layout.yml` and `rules.yml` schema
- `.opencode/references/obsidian-vault.md` — Obsidian MCP terminology and vault workflow
- `pyscript/AGENTS.md` — mandatory safety gates for any PyScript edit
