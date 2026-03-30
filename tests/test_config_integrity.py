import re
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
LAYOUT_PATH = ROOT / "layout.yml"
RULES_PATH = ROOT / "rules.yml"
DEVICES_PATH = ROOT / "devices.yml"
DISCOVERED_PATH = ROOT / "discovered.yml"

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
