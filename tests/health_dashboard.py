import datetime
import os
from collections import defaultdict
from pathlib import Path

import requests
import yaml


OFFLINE_STATES = {"unavailable", "unknown"}
SENSOR_OFFLINE_STATES = OFFLINE_STATES | {"none"}
IGNORED_ENTITY_PREFIXES = (
    "light.browser_mod",
    "light.meta_",
    "light.servicedriver",
    "light.all",
)
IGNORED_ENTITY_KEYWORDS = (
    "default_fade",
    "bulb_effect",
)
IGNORED_OUTPUT_SUFFIXES = (
    "_identify",
    "_battery",
    "_firmware",
)
ENV_TOKEN_KEYS = (
    "HA_TOKEN",
    "HASS_TOKEN",
    "HOMEASSISTANT_TOKEN",
)


def _load_env_file(path):
    values = {}
    if not path.exists() or not path.is_file():
        return values
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def _get_runtime_env():
    root = Path(__file__).resolve().parents[1]
    merged = {}
    for env_path in (root / ".env", root.parent / ".env"):
        merged.update(_load_env_file(env_path))
    for key in ("HA_URL", "OBSIDIAN_HEALTH_DASHBOARD_PATH", "OBSIDIAN_PATH", *ENV_TOKEN_KEYS):
        if os.getenv(key):
            merged[key] = os.getenv(key)
    return merged


def _load_yaml(path):
    if not path.exists():
        return {}
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def _is_ignored_entity(entity_id):
    if any(entity_id.startswith(prefix) for prefix in IGNORED_ENTITY_PREFIXES):
        return True
    return any(keyword in entity_id for keyword in IGNORED_ENTITY_KEYWORDS)


def _is_ignored_output_name(output_name):
    return output_name.endswith(IGNORED_OUTPUT_SUFFIXES)


def _normalize_output_entity(output_name):
    if "." in output_name:
        return output_name
    return f"light.{output_name}"


def _device_type_to_domain(device_type):
    mapping = {
        "light": "light",
        "plug": "switch",
        "fan": "fan",
        "speaker": "media_player",
        "blind": "cover",
        "television": "media_player",
        "sensor": "sensor",
        "motion": "binary_sensor",
        "presence": "binary_sensor",
    }
    return mapping.get(device_type)


def _discover_output_entity(output_name, discovered_cfg):
    candidate = _normalize_output_entity(output_name)
    if candidate in discovered_cfg:
        return candidate

    if output_name in discovered_cfg and isinstance(discovered_cfg[output_name], dict):
        domains = discovered_cfg[output_name].get("domains", []) or []
        for domain in ("light", "switch", "fan", "media_player", "cover"):
            if domain in domains:
                return f"{domain}.{output_name}"

    if output_name.startswith("hue_") and output_name.endswith("_firmware"):
        return f"update.{output_name}"

    if output_name in discovered_cfg:
        cfg = discovered_cfg[output_name] or {}
        dtype = cfg.get("type")
        if dtype == "plug":
            return f"switch.{output_name}"
        if dtype == "fan":
            return f"fan.{output_name}"
        if dtype == "blind":
            return f"cover.{output_name}"
        if dtype == "speaker":
            return f"media_player.{output_name}"
    return candidate


def _resolve_input_entity(raw_sensor, discovered_cfg):
    if "." in raw_sensor:
        return raw_sensor, True

    if raw_sensor.startswith("motion_sensor_"):
        for suffix in ("_ias_zone", "_iaszone", "_occupancy"):
            return f"binary_sensor.{raw_sensor}{suffix}", True

    if raw_sensor.startswith("presence_sensor_"):
        if raw_sensor == "presence_sensor_living_room_front_room":
            return "binary_sensor.presence_sensor_living_room_front", True
        return f"binary_sensor.{raw_sensor}", True

    if raw_sensor.endswith("_temp_temperature"):
        return f"sensor.{raw_sensor}", True

    if raw_sensor == "service_input":
        return "sensor.service_input", False

    if raw_sensor in discovered_cfg and isinstance(discovered_cfg[raw_sensor], dict):
        domains = discovered_cfg[raw_sensor].get("domains", []) or []
        for domain in ("binary_sensor", "sensor"):
            if domain in domains:
                return f"{domain}.{raw_sensor}", True

    return f"sensor.{raw_sensor}", False


def _build_automation_inventory(root):
    layout = _load_yaml(root / "layout.yml")
    devices = _load_yaml(root / "devices.yml")
    discovered = _load_yaml(root / "discovered.yml")
    rules = _load_yaml(root / "rules.yml")

    outputs = {}
    sensors = {}
    area_outputs = defaultdict(set)
    room_status = {}

    for area_name, area_data in layout.items():
        if not isinstance(area_data, dict):
            continue

        room_has_inputs = False
        room_has_motion = False
        inputs = area_data.get("inputs", {}) or {}
        for input_type, entries in inputs.items():
            if input_type in {"motion", "presence", "temperature", "contact"}:
                room_has_inputs = True
            if input_type == "motion":
                room_has_motion = True

            for raw_sensor in entries or []:
                sensor_id, resolved = _resolve_input_entity(raw_sensor, discovered)
                sensors[sensor_id] = {
                    "entity_id": sensor_id,
                    "area": area_name,
                    "input_type": input_type,
                    "raw_sensor": raw_sensor,
                    "resolved": resolved,
                }

        room_outputs = []
        for key in ("outputs", "power_outputs"):
            for output_name in area_data.get(key, []) or []:
                if _is_ignored_output_name(output_name):
                    continue
                bare_name = output_name
                entity_id = _discover_output_entity(output_name, discovered)

                if bare_name in devices and isinstance(devices[bare_name], dict):
                    dtype = devices[bare_name].get("type")
                    domain = _device_type_to_domain(dtype)
                    if domain:
                        entity_id = f"{domain}.{bare_name}"
                elif bare_name in discovered and isinstance(discovered[bare_name], dict):
                    dtype = discovered[bare_name].get("type")
                    domain = _device_type_to_domain(dtype)
                    if domain:
                        entity_id = f"{domain}.{bare_name}"
                if _is_ignored_entity(entity_id):
                    continue
                source = []
                if bare_name in devices:
                    source.append("devices")
                if bare_name in discovered:
                    source.append("discovered")
                if not source:
                    source.append("layout")

                outputs[entity_id] = {
                    "entity_id": entity_id,
                    "bare_name": bare_name,
                    "area": area_name,
                    "sources": source,
                    "kind": key,
                }
                area_outputs[area_name].add(entity_id)
                room_outputs.append(entity_id)

        room_status[area_name] = {
            "has_critical_inputs": room_has_inputs,
            "has_motion_input": room_has_motion,
            "configured_outputs": len(room_outputs),
            "rule_on": False,
            "rule_off": False,
        }

    for rule in rules.values():
        if not isinstance(rule, dict):
            continue
        if rule.get("trigger_prefix") != "motion_":
            continue
        required_tags = set(rule.get("required_tags", []) or [])
        if "on" in required_tags:
            for area in room_status.values():
                area["rule_on"] = area["rule_on"] or True
        if "off" in required_tags:
            for area in room_status.values():
                area["rule_off"] = area["rule_off"] or True

    return {
        "outputs": outputs,
        "sensors": sensors,
        "area_outputs": dict(area_outputs),
        "room_status": room_status,
    }


def _fetch_ha_states(base_url, token):
    if not token:
        return None, "Missing HA token (set HA_TOKEN/HASS_TOKEN/HOMEASSISTANT_TOKEN)."
    endpoint = f"{base_url.rstrip('/')}/api/states"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    try:
        response = requests.get(endpoint, headers=headers, timeout=10)
    except requests.RequestException as exc:
        return None, f"Unable to reach Home Assistant API: {exc}"
    if response.status_code != 200:
        return None, f"Home Assistant API returned {response.status_code}."
    try:
        payload = response.json()
    except ValueError:
        return None, "Home Assistant API response was not valid JSON."
    if not isinstance(payload, list):
        return None, "Home Assistant API /api/states payload was not a list."
    return payload, None


def _collect_test_summary(session, exitstatus):
    terminal = session.config.pluginmanager.get_plugin("terminalreporter")
    source_stats = getattr(terminal, "stats", None) or getattr(session, "stats", {})
    stats = {key: len(reports) for key, reports in source_stats.items()}
    collected = getattr(session, "testscollected", 0)
    passed = stats.get("passed", 0)
    if collected and not any(stats.get(key, 0) for key in ("passed", "failed", "error", "skipped")):
        passed = collected
    return {
        "status": "PASS" if exitstatus == 0 else "FAIL" if exitstatus == 1 else "INTERRUPTED" if exitstatus == 2 else "ERROR",
        "collected": collected,
        "passed": passed,
        "failed": stats.get("failed", 0),
        "errors": stats.get("error", 0),
        "skipped": stats.get("skipped", 0),
    }


def _collect_system_audit(inventory, states_payload):
    state_by_entity = {}
    for item in states_payload or []:
        entity_id = item.get("entity_id")
        if entity_id:
            state_by_entity[entity_id] = str(item.get("state", "unknown")).lower()

    outputs = inventory["outputs"]
    sensors = inventory["sensors"]
    room_status = inventory["room_status"]

    offline_outputs = []
    missing_outputs = []
    online_outputs = []

    for entity_id, cfg in sorted(outputs.items()):
        state = state_by_entity.get(entity_id)
        if state is None:
            missing_outputs.append((entity_id, cfg["area"], "missing"))
        elif state in OFFLINE_STATES:
            offline_outputs.append((entity_id, cfg["area"], state))
        else:
            online_outputs.append((entity_id, cfg["area"], state))

    offline_sensors = []
    missing_sensors = []
    online_sensors = []

    unresolved_inputs = []
    for entity_id, cfg in sorted(sensors.items()):
        if not cfg.get("resolved"):
            unresolved_inputs.append((cfg["raw_sensor"], cfg["area"], cfg["input_type"]))
            continue
        state = state_by_entity.get(entity_id)
        if state is None and cfg["input_type"] == "motion":
            fallback_candidates = [
                entity_id.replace("_ias_zone", "_iaszone"),
                entity_id.replace("_iaszone", "_occupancy"),
                entity_id.replace("_ias_zone", "_occupancy"),
            ]
            for candidate in fallback_candidates:
                if candidate in state_by_entity:
                    state = state_by_entity[candidate]
                    break
        if state is None:
            missing_sensors.append((entity_id, cfg["area"], cfg["input_type"], "missing"))
        elif state in SENSOR_OFFLINE_STATES:
            offline_sensors.append((entity_id, cfg["area"], cfg["input_type"], state))
        else:
            online_sensors.append((entity_id, cfg["area"], cfg["input_type"], state))

    live_automation_outputs = set(outputs)
    configured_domains = {entity.split(".", 1)[0] for entity in live_automation_outputs}
    live_house_outputs = {
        entity_id
        for entity_id in state_by_entity
        if entity_id.split(".", 1)[0] in configured_domains
        and not _is_ignored_entity(entity_id)
    }
    untracked_live_outputs = sorted(live_house_outputs - live_automation_outputs)

    drift_buckets = {
        "likely_config_targets": [],
        "grouped_entities": [],
        "variant_entities": [],
        "other_helpers": [],
    }
    for entity_id in untracked_live_outputs:
        name = entity_id.split(".", 1)[1]
        if name.endswith("_lights") or name.endswith("_group") or name in {"everything", "front_group", "work_group"}:
            drift_buckets["grouped_entities"].append(entity_id)
        elif any(token in name for token in ("_warm_rgb", "_cold_rgb", "_child_lock", "_display", "_do_not_disturb", "_inverted")):
            drift_buckets["variant_entities"].append(entity_id)
        elif any(token in name for token in ("plug_", "socket_", "splug_")) and entity_id.startswith(("fan.", "switch.")):
            drift_buckets["other_helpers"].append(entity_id)
        else:
            drift_buckets["likely_config_targets"].append(entity_id)

    room_rows = []
    for area_name, room in sorted(room_status.items()):
        configured_outputs = [entity for entity, cfg in outputs.items() if cfg["area"] == area_name]
        online = sum(1 for entity in configured_outputs if entity in dict((e, s) for e, _a, s in online_outputs))
        offline = sum(1 for entity in configured_outputs if entity in dict((e, s) for e, _a, s in offline_outputs))
        missing = sum(1 for entity in configured_outputs if entity in dict((e, s) for e, _a, s in missing_outputs))

        if room["configured_outputs"] == 0 and room["has_critical_inputs"]:
            status = "INCOMPLETE"
        elif missing > 0 or offline > 0:
            status = "DEGRADED"
        elif room["configured_outputs"] > 0:
            status = "HEALTHY"
        else:
            status = "NOT_AUTOMATED"

        room_rows.append({
            "area": area_name,
            "outputs": room["configured_outputs"],
            "online": online,
            "offline": offline,
            "missing": missing,
            "critical_inputs": room["has_critical_inputs"],
            "motion_input": room["has_motion_input"],
            "status": status,
        })

    def pct(num, den):
        return (num / den * 100.0) if den else 0.0

    return {
        "outputs_total": len(outputs),
        "outputs_online": len(online_outputs),
        "outputs_offline": len(offline_outputs),
        "outputs_missing": len(missing_outputs),
        "output_health_pct": pct(len(online_outputs), len(outputs)),
        "sensors_total": len(sensors),
        "sensors_online": len(online_sensors),
        "sensors_offline": len(offline_sensors),
        "sensors_missing": len(missing_sensors),
        "sensor_health_pct": pct(len(online_sensors), len(sensors)),
        "coverage_pct": pct(len(live_automation_outputs & live_house_outputs), len(live_automation_outputs)),
        "offline_outputs": offline_outputs,
        "missing_outputs": missing_outputs,
        "offline_sensors": offline_sensors,
        "missing_sensors": missing_sensors,
        "unresolved_inputs": unresolved_inputs,
        "untracked_live_outputs": untracked_live_outputs,
        "drift_buckets": drift_buckets,
        "room_rows": room_rows,
    }


def _render_table(headers, rows):
    if not rows:
        return ""
    widths = [len(h) for h in headers]
    for row in rows:
        for idx, cell in enumerate(row):
            widths[idx] = max(widths[idx], len(str(cell)))
    header = "| " + " | ".join(str(headers[i]).ljust(widths[i]) for i in range(len(headers))) + " |"
    sep = "| " + " | ".join("-" * widths[i] for i in range(len(headers))) + " |"
    body = ["| " + " | ".join(str(row[i]).ljust(widths[i]) for i in range(len(headers))) + " |" for row in rows]
    return "\n".join([header, sep, *body])


def _render_dashboard(audit, test_summary, ha_error):
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    overall = "HEALTHY" if audit["outputs_offline"] == 0 and audit["outputs_missing"] == 0 else "DEGRADED"

    lines = [
        "# Home Assistant Automation Audit",
        "",
        f"Last Updated: {timestamp}",
        "",
        "## Executive Summary",
        "What this means: top-level health for automation-critical outputs and inputs only.",
        "",
        f"- Status: {overall}",
        f"- Output Health: {audit['output_health_pct']:.1f}% online ({audit['outputs_online']}/{audit['outputs_total']})",
        f"- Sensor Health: {audit['sensor_health_pct']:.1f}% online ({audit['sensors_online']}/{audit['sensors_total']})",
        f"- Config Coverage: {audit['coverage_pct']:.1f}%",
        f"- Test Status: {test_summary['status']} ({test_summary['passed']}/{test_summary['collected']} passed)",
        "",
        "## Critical Issues",
        "What this means: entities that are configured for automation but are currently offline, unavailable, or missing from HA.",
        "",
    ]

    critical_rows = []
    for entity_id, area, state in audit["offline_outputs"]:
        critical_rows.append([entity_id, area, state, "output_offline"])
    for entity_id, area, state in audit["missing_outputs"]:
        critical_rows.append([entity_id, area, state, "output_missing"])
    for entity_id, area, input_type, state in audit["offline_sensors"]:
        critical_rows.append([entity_id, area, state, f"sensor_offline:{input_type}"])
    for entity_id, area, input_type, state in audit["missing_sensors"]:
        critical_rows.append([entity_id, area, state, f"sensor_missing:{input_type}"])

    lines.append(_render_table(["Entity", "Area", "State", "Issue"], critical_rows) or "- None")

    lines.extend([
        "",
        "## Input Mapping Gaps",
        "What this means: layout inputs that the audit cannot confidently map to a real HA entity id. If this section is non-empty, sensor health is undercounted for those inputs.",
        "",
        _render_table(
            ["Input", "Area", "Type"],
            [[raw, area, input_type] for raw, area, input_type in audit["unresolved_inputs"]],
        ) or "- None",
    ])

    lines.extend([
        "",
        "## Room Audit",
        "What this means: per-room summary of configured outputs plus whether the room has critical inputs. `INCOMPLETE` means the room has inputs but no configured outputs.",
        "",
        _render_table(
            ["Room", "Outputs", "Online", "Offline", "Missing", "Inputs", "Motion", "Status"],
            [
                [
                    row["area"],
                    row["outputs"],
                    row["online"],
                    row["offline"],
                    row["missing"],
                    "yes" if row["critical_inputs"] else "no",
                    "yes" if row["motion_input"] else "no",
                    row["status"],
                ]
                for row in audit["room_rows"]
                if row["outputs"] > 0 or row["critical_inputs"]
            ],
        ) or "- None",
        "",
        "## Drift Audit",
        "What this means: live HA entities in automation-relevant domains that are not currently modeled in the pyscript config.",
        "",
        f"- Total untracked live automation-domain entities: {len(audit['untracked_live_outputs'])}",
    ])

    bucket_descriptions = [
        ("likely_config_targets", "Likely Config Targets", "Real entities that probably should be modeled or intentionally excluded."),
        ("grouped_entities", "Grouped / Meta Entities", "Aggregated room/group entities that are often useful but not always necessary to model directly."),
        ("variant_entities", "Variant Child Entities", "Color, mode, or feature-specific child entities that usually should not be primary automation targets."),
        ("other_helpers", "Other Helpers", "Likely helper or duplicate control surfaces rather than primary automation targets."),
    ]
    for bucket_key, title, description in bucket_descriptions:
        bucket = audit["drift_buckets"][bucket_key]
        lines.extend([
            "",
            f"### {title}",
            description,
            "",
        ])
        if bucket:
            lines.extend([f"- {entity_id}" for entity_id in bucket[:15]])
            if len(bucket) > 15:
                lines.append(f"- ... {len(bucket) - 15} more")
        else:
            lines.append("- None")

    lines.extend([
        "",
        "## Notes",
        "- Scope is automation-critical entities only (outputs + critical inputs).",
        "- Helper entities are excluded (`browser_mod*`, `default_fade*`, `bulb_effect*`, etc.).",
    ])

    if ha_error:
        lines.append(f"- HA API status: {ha_error}")
    else:
        lines.append("- HA API status: OK")

    return "\n".join(lines) + "\n"


def _default_dashboard_path():
    return Path("~/workspace/Obsidian/Projects/Areas/Home/Homeassistant/Automation/System Health Dashboard.md").expanduser()


def _resolve_dashboard_path(runtime_env):
    path = runtime_env.get("OBSIDIAN_HEALTH_DASHBOARD_PATH") or runtime_env.get("OBSIDIAN_PATH")
    return Path(path).expanduser() if path else _default_dashboard_path()


def generate_dashboard(session, exitstatus):
    root = Path(__file__).resolve().parents[1]
    runtime_env = _get_runtime_env()
    dashboard_path = _resolve_dashboard_path(runtime_env)
    dashboard_path.parent.mkdir(parents=True, exist_ok=True)

    ha_url = runtime_env.get("HA_URL", "http://localhost:8123")
    token = next((runtime_env.get(key) for key in ENV_TOKEN_KEYS if runtime_env.get(key)), None)

    inventory = _build_automation_inventory(root)
    states_payload, ha_error = _fetch_ha_states(ha_url, token)
    audit = _collect_system_audit(inventory, states_payload)
    test_summary = _collect_test_summary(session, exitstatus)
    dashboard_path.write_text(_render_dashboard(audit, test_summary, ha_error), encoding="utf-8")
