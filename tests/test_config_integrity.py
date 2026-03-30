import re
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
LAYOUT_PATH = ROOT / "layout.yml"
RULES_PATH = ROOT / "rules.yml"
DEVICES_PATH = ROOT / "devices.yml"
DISCOVERED_PATH = ROOT / "discovered.yml"
AUTOMATIONS_PATH = ROOT.parent / "automations.yaml"

AUTODISCOVERY_OUTPUT_RE = re.compile(r"^kauf_bulb_(default_fade|effect)_\d+$")
KNOWN_LEGACY_AUTODISCOVERY_OUTPUTS = {
    ("living_room", "kauf_bulb_default_fade_13"),
    ("living_room", "kauf_bulb_default_fade_2"),
    ("living_room", "kauf_bulb_default_fade_24"),
    ("living_room", "kauf_bulb_effect_18"),
    ("dining_room", "kauf_bulb_default_fade_8"),
    ("dining_room", "kauf_bulb_default_fade_9"),
    ("dining_room", "kauf_bulb_effect_17"),
    ("laundry_room", "kauf_bulb_default_fade_25"),
    ("laundry_room", "kauf_bulb_default_fade_4"),
    ("bedroom", "kauf_bulb_effect_15"),
    ("bedroom", "kauf_bulb_effect_16"),
}
VALID_DEVICE_TYPES = {
    "light",
    "blind",
    "speaker",
    "plug",
    "contact_sensor",
    "fan",
    "television",
    "sensor",
    "motion",
    "presence",
    "unknown",
}


def load_yaml(path):
    with open(path, "r", encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


def iter_area_outputs(layout):
    for area_name, area_data in layout.items():
        for output in area_data.get("outputs", []) or []:
            yield area_name, output


def iter_motion_inputs(layout):
    for area_name, area_data in layout.items():
        inputs = area_data.get("inputs", {}) or {}
        for sensor_name in inputs.get("motion", []) or []:
            yield area_name, sensor_name


def iter_service_inputs(layout):
    for area_name, area_data in layout.items():
        inputs = area_data.get("inputs", {}) or {}
        for input_entry in inputs.get("service", []) or []:
            if isinstance(input_entry, str):
                yield area_name, input_entry
            elif isinstance(input_entry, dict):
                name = input_entry.get("name")
                if name:
                    yield area_name, name


def rule_matches_required_tags(rule, required_tags):
    rule_tags = set(rule.get("required_tags", []) or [])
    return set(required_tags).issubset(rule_tags)


def test_layout_outputs_resolve_to_known_devices():
    layout = load_yaml(LAYOUT_PATH)
    devices = load_yaml(DEVICES_PATH)
    discovered = load_yaml(DISCOVERED_PATH)
    known_devices = set(devices) | set(discovered)

    missing = []
    for area_name, output in iter_area_outputs(layout):
        if output not in known_devices:
            missing.append((area_name, output))

    assert not missing, f"Unknown outputs in layout.yml: {missing}"


def test_no_new_raw_kauf_autodiscovery_output_names_are_added_to_layout():
    layout = load_yaml(LAYOUT_PATH)

    offenders = []
    for area_name, output in iter_area_outputs(layout):
        if AUTODISCOVERY_OUTPUT_RE.match(output) and (area_name, output) not in KNOWN_LEGACY_AUTODISCOVERY_OUTPUTS:
            offenders.append((area_name, output))

    assert not offenders, (
        "New raw kauf autodiscovery names should not be added directly to layout outputs; "
        f"add a manual devices.yml override instead: {offenders}"
    )


def test_motion_inputs_use_motion_sensor_naming_convention():
    layout = load_yaml(LAYOUT_PATH)
    invalid = []
    for area_name, sensor_name in iter_motion_inputs(layout):
        if "motion" not in sensor_name:
            invalid.append((area_name, sensor_name))

    assert not invalid, f"Motion inputs should use motion-sensor names: {invalid}"


def test_motion_rules_cover_both_off_tag_variants():
    layout = load_yaml(LAYOUT_PATH)
    rules = load_yaml(RULES_PATH)
    motion_rules = [
        rule
        for rule in rules.values()
        if (rule or {}).get("trigger_prefix") == "motion_"
    ]

    assert motion_rules, "Expected at least one motion rule in rules.yml"

    has_motion_detected_off = any(
        rule_matches_required_tags(rule, ["off", "motion_detected"])
        for rule in motion_rules
    )
    has_motion_occupancy_off = any(
        rule_matches_required_tags(rule, ["off", "motion_occupancy"])
        for rule in motion_rules
    )

    configured_motion_inputs = list(iter_motion_inputs(layout))
    assert configured_motion_inputs, "Expected at least one motion input in layout.yml"
    assert has_motion_detected_off, "rules.yml is missing off coverage for motion_detected (_ias_zone) sensors"
    assert has_motion_occupancy_off, "rules.yml is missing off coverage for motion_occupancy sensors"


def test_manual_device_override_types_are_known():
    devices = load_yaml(DEVICES_PATH)
    invalid = []
    for name, cfg in devices.items():
        dtype = (cfg or {}).get("type")
        if dtype not in VALID_DEVICE_TYPES:
            invalid.append((name, dtype))

    assert not invalid, f"devices.yml contains unknown type values: {invalid}"


def test_service_inputs_use_button_naming_convention():
    layout = load_yaml(LAYOUT_PATH)
    invalid = []
    for area_name, service_name in iter_service_inputs(layout):
        if not service_name.startswith("service_input_button_"):
            invalid.append((area_name, service_name))

    assert not invalid, f"Service inputs should start with service_input_button_: {invalid}"


def test_button_rules_use_local_scope_and_light_filter():
    rules = load_yaml(RULES_PATH)
    required = {
        "toggle_light_status": "service_input_button_single",
        "toggle_light_color": "service_input_button_double",
    }

    for rule_name, trigger_prefix in required.items():
        rule = rules.get(rule_name) or {}
        assert rule.get("trigger_prefix") == trigger_prefix, (
            f"{rule_name} trigger_prefix expected {trigger_prefix}, got {rule.get('trigger_prefix')}"
        )
        assert rule.get("scope_functions") == [{"get_local_scope": []}], (
            f"{rule_name} should use get_local_scope"
        )
        assert rule.get("device_type_filter") == ["light"], (
            f"{rule_name} should be light-only"
        )


def test_button_automations_use_named_service_inputs_without_scope_injection():
    automations = load_yaml(AUTOMATIONS_PATH)
    bad_scope = []
    bad_name = []
    bad_service = []

    allowed_pyscript_services = {
        "pyscript.create_event",
        "pyscript.button_6_power_off_bedroom",
        "pyscript.button_laundry_double",
        "pyscript.button_3_turn_all_off_bedroom_lamp",
        "pyscript.button_3_toggle_fan_bedroom_lamp",
        "pyscript.bedroom_shake_toggle_fan_button_6",
    }

    for automation in automations:
        trigger_block = automation.get("trigger") or automation.get("triggers") or []
        if isinstance(trigger_block, dict):
            trigger_block = [trigger_block]
        is_button_automation = any(
            isinstance(trigger, dict)
            and (
                str(trigger.get("type", "")).startswith("remote_button_")
                or trigger.get("type") == "device_shaken"
            )
            for trigger in trigger_block
        )
        if not is_button_automation:
            continue

        action = automation.get("action")
        if not isinstance(action, list):
            continue
        for step in action:
            service_name = step.get("service") or step.get("action")
            if not isinstance(service_name, str) or not service_name.startswith("pyscript."):
                continue

            if service_name not in allowed_pyscript_services:
                bad_service.append((automation.get("alias"), service_name))

            if service_name == "pyscript.create_event":
                data = step.get("data", {}) or {}
                device_name = data.get("device_name", "")
                if not device_name.startswith("service_input_button_"):
                    bad_name.append((automation.get("alias"), device_name))
                if "scope_functions" in data:
                    bad_scope.append(automation.get("alias"))

    assert not bad_service, f"Unexpected pyscript button services found in automations: {bad_service}"
    assert not bad_name, f"Button automations should use named button service_input devices: {bad_name}"
    assert not bad_scope, f"Button automations should not inject scope_functions: {bad_scope}"
