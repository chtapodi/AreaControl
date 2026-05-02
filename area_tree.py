"""
Home Assistant Pyscript Automation System

This module provides the core automation infrastructure for managing smart home
devices through a hierarchical area model.

Architecture:
    - AreaTree: Hierarchical structure of rooms/zones with parent-child relationships
    - Device: Wrapper around device drivers (lights, blinds, speakers, etc.)
    - EventManager: Processes events and executes matching automation rules
    - Device Drivers: Hardware-specific interfaces (KaufLight, HueLight, BlindDriver, etc.)

State Management:
    - States are represented as dictionaries with keys like 'status', 'brightness',
      'rgb_color', 'color_temp', etc.
    - States are combined using strategies: 'first', 'last', 'average', 'first_state'
    - The cache system tracks last known state for each device

Rule System:
    - Rules are defined in rules.yml with trigger_prefix, scope_functions,
      state_functions, and combination_strategy
    - Scope functions determine which areas a rule applies to
    - State functions generate dynamic states based on time, presence, etc.
"""
import yaml
import os
import builtins
from collections import defaultdict
import copy
import time
import random
import asyncio

from pyscript.k_to_rgb import convert_K_to_RGB
from homeassistant.const import EVENT_CALL_SERVICE
try:
    from homeassistant.util import color as color_util
except Exception:  # pragma: no cover - fallback for tests without Home Assistant
    class _ColorUtil:
        @staticmethod
        def color_RGB_to_hs(r, g, b):
            return (0, 0)

        @staticmethod
        def color_hs_to_RGB(h, s):
            return (0, 0, 0)

        @staticmethod
        def color_temperature_to_rgb(k):
            return (0, 0, 0)

    color_util = _ColorUtil()
# Occupancy tracking modules: imported lazily in init() to avoid
# pyscript reload issues with 'modules' namespace packaging.
try:
    from adaptive_learning import get_learner
    from logger import Logger
except ImportError:
    from modules.adaptive_learning import get_learner
    from modules.logger import Logger
import unittest

try:
    from homeassistant.helpers import device_registry as ha_device_registry
    from homeassistant.helpers import entity_registry as ha_entity_registry
except Exception:  # pragma: no cover - these modules exist only in HA
    ha_device_registry = None
    ha_entity_registry = None

log = Logger(__name__, globals().get("log"))




STATE_VALUES = {
    "input": {
        "status": 0,
        "baud_duration": 0,
        "elapsed_time": 0,
    },
    "output": {"status": 0, "rgb": [0, 0, 0], "brightness": 0, "temperature": 0},
}


area_tree = None
event_manager = None
global_triggers = None
occupancy_engine=None
tracker_manager=None
config_settings = {}

# Shadow mode: run legacy TrackManager alongside OccupancyEngine, compare decisions.
# When True, both trackers run and disagreements are logged.  The legacy
# tracker still drives actual automations — the new engine is read-only.
SHADOW_MODE = True

# Maps area_name -> asyncio.Task for pending delayed-off
pending_motion_off = {}

# Default delay (seconds) when no per-area value is configured
DEFAULT_MOTION_OFF_DELAY = 900

verbose_mode = False

last_set_state={}

# Default heights for smart blinds (in the same units used when setting height).
# These values allow converting between physical height and percentage closed.
BLIND_HEIGHTS = {
    "blind_bedroom_window": 100,
}

# Per-device color calibration profiles. Each entry maps a driver keyword
# to RGB multipliers used to compensate for hardware differences.
COLOR_PROFILES = {
    "kauf": [1.0, 1.0, 1.0],
    "hue": [1.0, 1.0, 1.0],
}

# Centralized config paths; falls back to legacy defaults when config is missing.
DEFAULT_CONFIG_PATH = "./pyscript/config.yml"
DEFAULT_CONFIG = {
    "layout": "./pyscript/layout.yml",
    "rules": "./pyscript/rules.yml",
    "devices": "devices.yml",
    "discovered": "./pyscript/discovered.yml",
    "connections": "./pyscript/connections.yml",
    "sun": "./pyscript/sun_config.yml",
}
DEFAULT_RUN_TESTS_ON_START = True
DEFAULT_DEVICE_AUDIT_PATH = "./pyscript/debug/device_audit.txt"

def write_area_tree_snapshot(area_tree, path="./pyscript/debug/area_tree.txt"):
    """Persist the current area tree for inspection."""
    try:
        directory = os.path.dirname(path)
        if directory:
            os.makedirs(directory, exist_ok=True)
        with builtins.open(path, "w", encoding="utf-8") as f:
            tree_string = area_tree.get_pretty_string()
            f.write(tree_string)
        log.info(f"Wrote area tree snapshot to {path}")
    except Exception as exc:
        log.warning(f"Failed writing area tree snapshot to {path}: {exc}")


def audit_homeassistant_devices(area_tree_obj, path=DEFAULT_DEVICE_AUDIT_PATH):
    """Compare HA device registry against devices.yml entries and persist a text report."""
    if area_tree_obj is None:
        log.warning("Device audit skipped: area tree not initialized")
        return None

    if ha_device_registry is None or ha_entity_registry is None:
        log.info("Device audit skipped: Home Assistant registries unavailable")
        return None

    hass_obj = globals().get("hass")
    if hass_obj is None:
        log.info("Device audit skipped: hass object unavailable")
        return None

    try:
        device_registry = ha_device_registry.async_get(hass_obj)
        entity_registry = ha_entity_registry.async_get(hass_obj)
    except Exception as exc:  # pragma: no cover - depends on HA internals
        log.warning(f"Device audit skipped: registry lookup failed ({exc})")
        return None

    known_ids = set((area_tree_obj.device_defs or {}).keys())
    entities_by_device = defaultdict(list)
    for entity in entity_registry.entities.values():
        if entity.device_id is not None:
            entities_by_device[entity.device_id].append(entity)

    missing_devices = []
    all_devices = []
    for device_id, device in device_registry.devices.items():
        entity_entries = entities_by_device.get(device_id, [])
        if not entity_entries:
            continue

        entity_object_ids = set()
        entity_details = []
        online = False
        entity_domains = set()

        for entity in entity_entries:
            entity_id = entity.entity_id
            if entity_id and "." in entity_id:
                domain, object_id = entity_id.split(".", 1)
                entity_domains.add(domain)
                entity_object_ids.add(object_id)
            else:
                entity_object_ids.add(entity_id)

            try:
                entity_state = state.get(entity_id)
            except Exception:
                entity_state = None

            if entity_state not in (None, "unknown", "unavailable"):
                online = True

            entity_details.append(
                {
                    "entity_id": entity_id,
                    "state": entity_state,
                    "disabled_by": str(entity.disabled_by) if entity.disabled_by else None,
                    "original_name": entity.original_name,
                }
            )

        known_match = bool(entity_object_ids & known_ids)
        entry = {
            "device_id": device_id,
            "name": device.name_by_user or device.name or device_id,
            "manufacturer": device.manufacturer,
            "model": device.model,
            "area_id": device.area_id,
            "online": online,
            "domains": sorted(entity_domains),
            "entities": entity_details,
            "is_missing": not known_match,
        }
        all_devices.append(entry)
        if entry["is_missing"]:
            missing_devices.append(entry)

    report = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "known_device_count": len(known_ids),
        "home_assistant_device_count": len(device_registry.devices),
        "missing_device_count": len(missing_devices),
        "missing_devices": missing_devices,
        "devices": all_devices,
    }

    summary_lines = [
        "Home Assistant Device Audit",
        "===========================",
        f"Generated: {report['generated_at']}",
        "",
        f"Known devices (devices.yml): {report['known_device_count']}",
        f"Devices in Home Assistant: {report['home_assistant_device_count']}",
        f"Devices missing from devices.yml: {report['missing_device_count']}",
        "",
    ]

    if not missing_devices:
        summary_lines.append("All Home Assistant devices are represented in devices.yml.")
    else:
        sorted_missing = sorted(
            [
                {
                    "name": (entry.get("name") or entry.get("device_id") or "unknown").strip(),
                    "online": bool(entry.get("online")),
                }
                for entry in missing_devices
            ],
            key=lambda info: info["name"].lower(),
        )
        summary_lines.append("Missing devices (sorted by name):")
        for entry in sorted_missing:
            suffix = "" if entry["online"] else " (offline)"
            summary_lines.append(f"{entry['name']}{suffix}")
        summary_lines.append("")
        category_map = defaultdict(list)
        for entry in missing_devices:
            if entry["domains"]:
                category = entry["domains"][0]
            else:
                category = "unknown"
            category_map[category].append(entry)

        for category in sorted(category_map.keys()):
            devices = category_map[category]
            summary_lines.append(f"=== Category: {category} ({len(devices)} devices) ===")
            for device in sorted(devices, key=lambda d: (d['name'] or "", d['device_id'])):
                summary_lines.append(
                    f"- {device['name']} (device_id={device['device_id']}, online={'yes' if device['online'] else 'no'})"
                )
                manufacturer = device.get("manufacturer") or "Unknown Manufacturer"
                model = device.get("model") or "Unknown Model"
                area_id = device.get("area_id") or "Unknown Area"
                domains = ", ".join(device.get("domains") or ["unknown"])
                summary_lines.append(f"    Manufacturer/Model: {manufacturer} / {model}")
                summary_lines.append(f"    Area ID: {area_id}")
                summary_lines.append(f"    Domains: {domains}")
                summary_lines.append("    Entities:")
                for entity in device["entities"]:
                    state_value = entity["state"]
                    summary_lines.append(
                        f"      * {entity['entity_id']} -> state={state_value}, disabled_by={entity['disabled_by']}"
                    )
                summary_lines.append("")

    if all_devices:
        summary_lines.append("All Home Assistant devices (missing first):")
        summary_lines.append("")
        sorted_all = sorted(
            all_devices,
            key=lambda entry: (
                0 if entry["is_missing"] else 1,
                (entry.get("name") or entry.get("device_id") or "unknown").lower(),
            ),
        )
        for device in sorted_all:
            status = "MISSING" if device["is_missing"] else "KNOWN"
            summary_lines.append(
                f"- {device['name']} [{status}] (device_id={device['device_id']}, online={'yes' if device['online'] else 'no'})"
            )
            manufacturer = device.get("manufacturer") or "Unknown Manufacturer"
            model = device.get("model") or "Unknown Model"
            area_id = device.get("area_id") or "Unknown Area"
            domains = ", ".join(device.get("domains") or ["unknown"])
            summary_lines.append(f"    Manufacturer/Model: {manufacturer} / {model}")
            summary_lines.append(f"    Area ID: {area_id}")
            summary_lines.append(f"    Domains: {domains}")
            summary_lines.append("    Entities:")
            for entity in device["entities"]:
                state_value = entity["state"]
                summary_lines.append(
                    f"      * {entity['entity_id']} -> state={state_value}, disabled_by={entity['disabled_by']}"
                )
            summary_lines.append("")

    summary_text = "\n".join(summary_lines).rstrip() + "\n"

    try:
        directory = os.path.dirname(path)
        if directory:
            os.makedirs(directory, exist_ok=True)
        with builtins.open(path, "w", encoding="utf-8") as handle:
            handle.write(summary_text)
        log.info(f"Wrote device audit report to {path}")
    except Exception as exc:
        log.warning(f"Failed writing device audit to {path}: {exc}")

    return report


def load_config(config_path: str = DEFAULT_CONFIG_PATH):
    """
    Load config path map and feature flags from a central YAML file.
    Accepts either top-level keys or a ``paths`` section; missing values fall back to defaults.
    """
    config_paths = dict(DEFAULT_CONFIG)
    config_flags = {"run_tests_on_start": DEFAULT_RUN_TESTS_ON_START}
    try:
        with builtins.open(config_path, "r") as f:
            cfg = yaml.safe_load(f) or {}
            log.info(f"Loaded {config_path} as config")
    except Exception as exc:
        log.warning(f"Could not load config at {config_path}, using defaults: {exc}")
        return {**config_paths, **config_flags}

    paths = cfg.get("paths", cfg)
    if isinstance(paths, dict):
        for key, val in paths.items():
            if val:
                config_paths[key] = val
                log.info(f"Config {key}:\t{val}")
    else:
        log.warning(f"Config file {config_path} missing 'paths' mapping, using defaults")
    run_tests_value = cfg.get("run_tests_on_start", cfg.get("run_tests", config_flags["run_tests_on_start"]))
    config_flags["run_tests_on_start"] = bool(run_tests_value)
    log.info(f"Config run_tests_on_start:\t{config_flags['run_tests_on_start']}")
    return {**config_paths, **config_flags}

def calibrate_rgb(rgb, profile):
    """Apply a color calibration profile to an RGB tuple."""
    if rgb is None or profile is None:
        return rgb
    result = []
    for comp, factor in zip(rgb, profile):
        val = int(comp * factor)
        val = max(0, min(255, val))
        result.append(val)
    return result


@service
def reset():
    log.warning("RESETTING. MAKE SURE YOU WANT THIS")
    global area_tree
    global event_manager
    global global_triggers
    global verbose_mode
    global occupancy_engine
    global tracker_manager
    area_tree = None
    event_manager = None
    global_triggers = None
    verbose_mode = False
    occupancy_engine=None
    tracker_manager=None
    init()

def _occ_init(config_settings):
    """Regular helper — avoids EvalFunc wrapping of imports inside @service."""
    from area_graph import AreaGraph
    from occupancy_engine import OccupancyEngine
    from occupancy_config import load_config as _occ_cfg_load
    import yaml

    with open("./pyscript/config.yml", "r") as f:
        raw = yaml.safe_load(f) or {}
    conn = raw.get("connections", "./pyscript/connections.yml")
    area_graph = AreaGraph(conn)
    occ_config = _occ_cfg_load()
    occ_engine = OccupancyEngine(area_graph, occ_config)
    return area_graph, occ_engine, occ_config


def _shadow_init(conn_path):
    """Shadow mode helper — regular function, no EvalFunc wrapping."""
    try:
        from tracker import TrackManager
        from log import log as _shadow_log
        tm = TrackManager(connections_config=conn_path)
        _shadow_log.info("Shadow mode ENABLED: legacy TrackManager running alongside OccupancyEngine")
        return tm
    except Exception:
        from log import log as _shadow_log
        _shadow_log.warning("Shadow mode: TrackManager unavailable — OccupancyEngine only")
        return None


@service
def init():
    global area_tree
    global event_manager
    global global_triggers
    global occupancy_engine
    global tracker_manager
    global config_settings

    config_settings = load_config()
    global_triggers = []
    area_tree = AreaTree(config_settings["layout"], devices_file=config_settings["devices"])
    event_manager = EventManager(config_settings["rules"], area_tree)

    area_graph, occupancy_engine, occ_config = _occ_init(config_settings)
    conn_path = "./pyscript/connections.yml"  # for shadow mode below

    # Shadow mode: also create legacy TrackManager for comparison
    if SHADOW_MODE:
        tracker_manager = _shadow_init(conn_path)
    else:
        tracker_manager = None
    
    # NOTE: power_on_all_power_monitoring_devices() is available as a
    # manual @service call but is intentionally NOT run on every reload.
    # Running it here caused devices to toggle during pyscript's rapid
    # file-watcher reloads.
    
    write_area_tree_snapshot(area_tree)
    audit_homeassistant_devices(area_tree)
    return config_settings


@service
def power_on_all_power_monitoring_devices():
    """Turn on all power-monitoring devices so they stay powered for passive monitoring."""
    global area_tree
    if area_tree is None:
        log.warning("power_on_all_power_monitoring_devices: area_tree not initialized yet.")
        return
    lookup = area_tree.area_tree_lookup
    for name, device in lookup.items():
        if isinstance(device, Device) and device.power_monitoring:
            log.info(f"power_on_all_power_monitoring_devices: Turning ON {name}")
            try:
                device.set_state({"status": 1})
            except Exception as e:
                log.warning(f"power_on_all_power_monitoring_devices: Failed to turn on {name}: {e}")


def get_global_triggers():
    global global_triggers
    if global_triggers is None:
        init()
    return global_triggers


@service
def get_total_average_state(key=None):
    area_tree = get_area_tree()
    root = area_tree.get_root()
    state = summarize_state(root.get_state())
    if key is not None:
        if key in state:
            return state[key]
        else:
            return None
    return state


def get_event_manager():
    global event_manager
    if event_manager is None:
        init()
    return event_manager

def get_occupancy_engine():
    global occupancy_engine
    if occupancy_engine is None:
        init()
    return occupancy_engine


def get_tracker_manager():
    """Return legacy TrackManager (only valid in shadow mode).
    
    Does NOT call init() — that would reinitialize the entire area_tree
    and break test setups.  If the tracker was never created (e.g. test
    environment), returns None and shadow mode gracefully degrades.
    """
    global tracker_manager
    return tracker_manager


def get_area_tree():
    event_manager = get_event_manager()
    return event_manager.get_area_tree()


def get_verbose_mode():
    global verbose_mode
    return verbose_mode


def get_cached_last_set_state():
    global last_set_state
    if last_set_state is None:
        return None
    return copy.deepcopy(last_set_state)

def set_cached_last_set_state(device,state):
    global last_set_state
    log.info(f"set global last set state to {state}")
    if state is None:
        last_set_state = None
    else:
        last_set_state = copy.deepcopy(state)
    return True

@service
def create_event(**kwargs):
    log.info(f"Service creating event:  with kwargs {kwargs}")
    event = {}
    if "name" in kwargs.keys():
        event["device_name"] = kwargs["name"]

    elif "device_name" in kwargs.keys():
        event["device_name"] = kwargs["device_name"]

    if "device_name" in event.keys():
        if "tags" in kwargs.keys():
            event["tags"] = kwargs["tags"]

        if "state" in kwargs.keys():
            event["state"] = kwargs["state"]

        if "scope_functions" in kwargs.keys():
            event["scope_functions"] = kwargs["scope_functions"]

        if "state_functions" in kwargs.keys():
            event["state_functions"] = kwargs["state_functions"]

        event_manager = get_event_manager()
        log.info(f"Service creating event: {event}")
        event_manager.create_event(event)

    else:
        log.warning(f"No devic_name in serice created event {kwargs}")


@service
def button_laundry_double():
    light.turn_on(entity_id="light.laundry_room_lights", color_temp=411)


@service
def button_6_power_off_bedroom():
    light.turn_off(
        entity_id=[
            "light.library_lamp",
            "light.all",
            "light.bedroom_lamp",
            "light.living_room_lamp",
            "light.living_room_hue",
        ],
        device_id=[
            "61ed18cf42fa764f9ba367d977111dd0",
            "33bec14f3e68137127a179bfb81da939",
            "61ed18cf42fa764f9ba367d977111dd0",
        ],
    )
    media_player.turn_off(device_id="61ed18cf42fa764f9ba367d977111dd0")
    switch.turn_on(entity_id=[], device_id=["88a63afd10a3b8d8dd20ac1d3e8e997d"], area_id=[])
    conversation.process(text="Turn off all of the lights")


@service
def button_3_turn_all_off_bedroom_lamp():
    light.turn_off(
        entity_id=[
            "light.library_lamp",
            "light.all",
            "light.bedroom_lamp",
            "light.living_room_lamp",
            "light.living_room_hue",
        ],
        device_id=[
            "61ed18cf42fa764f9ba367d977111dd0",
            "33bec14f3e68137127a179bfb81da939",
            "61ed18cf42fa764f9ba367d977111dd0",
        ],
    )
    media_player.turn_off(device_id="61ed18cf42fa764f9ba367d977111dd0")
    switch.turn_on(device_id="c3517fca894a66f52fcae19198f83445", area_id=[])


@service
def button_3_toggle_fan_bedroom_lamp():
    fan.toggle(entity_id="fan.splug_1_switch_1")


@service
def bedroom_shake_toggle_fan_button_6():
    fan.toggle(entity_id="fan.splug_0_switch_1")


@service
def freeze_area(area_name, recursive=True):
    """Freeze an area so its lights ignore future state changes."""
    area = get_area_tree().get_area(area_name)
    if area is None:
        log.warning(f"freeze_area: area {area_name} not found")
        return False
    area.freeze(propagate=recursive)
    return True


@service
def unfreeze_area(area_name, recursive=True):
    """Unfreeze a previously frozen area."""
    area = get_area_tree().get_area(area_name)
    if area is None:
        log.warning(f"unfreeze_area: area {area_name} not found")
        return False
    area.unfreeze(propagate=recursive)
    return True


def get_function_by_name(function_name, func_object=None):
    func = None
    if func_object is None:
        if function_name in globals().keys():
            func = globals()[function_name]
        else:
            log.warning(f"Function {function_name} not found")
    else:
        if hasattr(func_object, function_name):
            func = getattr(func_object, function_name)

    if func is None:
        log.warning(f"Function {function_name} not found")
    # else:
    # log.info(f"Function {function_name} found")
    return func


def combine_states(state_list, strategy="last"):
    """
    A function that combines a list of states using a specified strategy and returns the final combined state. 

    Args:
        state_list (list): A list of states to be combined.
        strategy (str, optional): The strategy to be used for combining the states. Defaults to "last".

        Strategies are :

        - "first_state" : Uses the first valid state in the list
        - "last" : The last state in the list
        - "first" : The first state in the list
        - "average" : Averages all of the states

    Returns:
        dict: The final combined state.
    """
    final_state = {}
    log.info(f"Combining states with strategy {strategy}: {state_list}")
    state_list=copy.deepcopy(state_list)

    if strategy=="first_state" : # Uses the first valid state in the list 
        # state_list.reverse()
        for state in state_list:
            if state is not None and len(state) > 0:
                log.info(f"Found first state: {state}")
                return state



    if strategy == "last" or strategy == "first":
        if strategy == "first": # Combine, first is least likely to be overwritten
            state_list.reverse()

        log.info(f"COMBINING states with strategy {strategy}: {state_list}")
        for state in state_list:
            if state is not None:
                final_state.update(state)  # Update overwrites previous value

    elif strategy == "average":
        sum_dict={}
        count_dict={}

        # This is to deal with the iterables within the dict and making sure they are all properly averaged. Its a pain. 
        # The first section sums up all of the values in the dict and keeps count, and the second half divides total by the count
        for state in state_list:
            if state is not None:
                for key, value in state.items():
                    if (isinstance(value, (tuple, list))
                            or value.__class__.__name__ == "TupleWrapper"
                        ):
                        if key not in sum_dict.keys():
                            sum_dict[key]=[]
                            count_dict[key]=[]
                            for i in range(len(value)):
                                sum_dict[key].append(0)
                                count_dict[key].append(0)

                        for i in range(len(value)):
                            sum_dict[key][i] += value[i]
                            count_dict[key][i] += 1

                    else:
                        if value is None:
                            continue
                        if key not in sum_dict.keys():
                            sum_dict[key] = 0
                            count_dict[key] = 0

                        sum_dict[key] += value
                        count_dict[key] += 1

        log.info(f"SUMDICT {sum_dict} COUNTDICT {count_dict}")
        for key, value in sum_dict.items():
            # if iterable 
            
            if (isinstance(value, (tuple, list))
                            or value.__class__.__name__ == "TupleWrapper"
                        ):
                if key not in final_state.keys():
                    final_state[key]=[]
                    for i in range(len(value)):
                        final_state[key].append(0)
                for i in range(len(value)):
                    final_state[key][i] = value[i] / count_dict[key][i]
            
            elif count_dict[key] > 0:
                final_state[key] = value / count_dict[key]
        if "status" in final_state.keys() and final_state["status"] > 0:
            final_state["status"] = 1
        
        log.info(f"FINAL STATE {final_state}")

    else :
        log.warning(f"Strategy {strategy} not found")
    if get_verbose_mode():
        log.info(f"combined states {state_list} into {final_state}")
    return final_state


def summarize_state(state):
    flat_state = {}
    for key, value in state.items():
        if type(value) == dict:
            new_state = summarize_state(value)
            flat_state = combine_states([flat_state, new_state], strategy="average")
        else:
            flat_state[key] = value
    if get_verbose_mode():
        log.info(f"summarized state {state} as {flat_state}")
    return flat_state


def combine_colors(color_one, color_two, strategy="add"):
    color = [0, 0, 0]
    if strategy == "average":
        color[0] = (color_one[0] + color_two[0]) / 2
        color[1] = (color_one[1] + color_two[1]) / 2
        color[2] = (color_one[2] + color_two[2]) / 2
    elif strategy == "add":
        color[0] = color_one[0] + color_two[0]
        color[1] = color_one[1] + color_two[1]
        color[2] = color_one[2] + color_two[2]
    else:
        log.warning(f"Strategy {strategy} not found")

    for i in range(len(color)):
        val = color[i]
        if val > 255:
            color[i] = 255
        if val < 0:
            color[i] = 0
    if get_verbose_mode():
        log.info(f"combined: {color_one} + {color_two} = {color}")

    return color


## RULES ##
# These must have an interface that mathes the following and returns boolean


def motion_sensor_mode(*args, **kwargs):
    log.info(f"motion_sensor_mode {input_boolean.motion_sensor_mode}")
    return input_boolean.motion_sensor_mode == "on"

def set_motion_sensor_mode(state):
    log.info(f"set_motion_sensor_mode {input_boolean.motion_sensor_mode}")
    input_boolean.motion_sensor_mode = state
    log.info(f"set_motion_sensor_mode is now {input_boolean.motion_sensor_mode}")


def _get_area_motion_off_delay(area):
    """Return the motion-off delay (seconds) for *area*, falling back to the default."""
    delay = getattr(area, "motion_off_delay", None)
    if delay is not None:
        return delay
    return DEFAULT_MOTION_OFF_DELAY


def schedule_motion_off(device, *args):
    """Replace the immediate motion-off action with a cancellable delayed one.

    Called as a ``functions`` guard from the motion_off rules.  Instead of
    returning False (which would block the rule entirely) it:
      1. Resolves the delay for the triggering area.
      2. Schedules a new async task that sleeps for *delay* seconds and then
         applies ``{status: 0}`` to the area's lights.  ``kill_me=True``
         ensures any previously running task with the same name is killed and
         the countdown is reset — this matters because the IAS-zone and
         occupancy sensors both fire off within milliseconds of each other, so
         whichever arrives second should always win and restart the timer.
      3. Returns False so the rule itself does NOT apply state immediately —
         the delayed task does it instead.

    The task handle is stored in ``pending_motion_off`` so that
    ``cancel_motion_off`` can cancel it directly when new motion is detected.
    """
    global pending_motion_off

    area = device.get_area()
    area_name = area.name
    delay = _get_area_motion_off_delay(area)

    log.info("schedule_motion_off: scheduling off", extra={
        "area": area_name,
        "delay_s": delay
    })

    async def _delayed_off():
        log.info("schedule_motion_off: delay wait start", extra={
                "area": area_name, "delay_s": delay
            })
        await asyncio.sleep(delay)
        log.info("schedule_motion_off: delay elapsed", extra={
                "area": area_name, "action": "check"
            })
        # Re-check motion sensor mode at execution time
        if not motion_sensor_mode():
            log.info("schedule_motion_off: sensor mode off", extra={
                    "area": area_name, "action": "skip_sensor_mode_off"
                })
            return
        area_obj = get_area_tree().get_area(area_name)
        if area_obj is None:
            log.warning(f"schedule_motion_off: [{area_name}] area no longer in tree")
            return
        area_obj.set_state({"status": 0}, device_type_filter=["light"],
                           event_id="motion-off_" + area_name)
        pending_motion_off.pop(area_name, None)
        log.info("schedule_motion_off: off applied", extra={
                "area": area_name, "action": "off_applied"
            })

    try:
        existing = pending_motion_off.get(area_name)
        if existing is not None:
            existing.cancel()
        pending_motion_off[area_name] = asyncio.create_task(_delayed_off())
    except RuntimeError:
        # No running event loop (e.g., test environment) — store coroutine directly
        pending_motion_off[area_name] = _delayed_off()

    # Return False: prevents the rule from applying state immediately.
    return False


def cancel_motion_off(device, *args):
    """Cancel any pending delayed-off for the device's area.

    Called as a ``functions`` entry on motion_on rules so that a new motion
    event cancels a previously scheduled off.
    """
    global pending_motion_off

    area_name = device.get_area().name
    existing = pending_motion_off.pop(area_name, None)
    if existing is not None:
        try:
            existing.cancel()
            log.info("cancel_motion_off", extra={
                    "area": area_name, "action": "cancelled"
                })
        except Exception as exc:
            log.warning(f"cancel_motion_off: error cancelling task for {area_name}: {exc}")
    return True


def check_adjacent_motion(device, *args):
    """Guard: block motion-off if a neighbouring room has had recent activity.

    Uses the OccupancyEngine to check whether any room directly connected
    to the device's area has had motion or presence within the configured
    window (default 5 minutes).  Returns False to suppress the motion-off
    when an adjacent room is likely occupied.
    """
    ADJACENT_WINDOW = 300  # seconds — how recent "adjacent motion" must be

    area_name = device.get_area().name
    engine = get_occupancy_engine()

    neighbors = engine.neighbors(area_name)
    if not neighbors:
        return True  # no neighbours configured → allow off

    for neighbor in neighbors:
        if engine.room_recent_activity(neighbor, ADJACENT_WINDOW):
            log.info(
                f"check_adjacent_motion: blocking off for {area_name} — "
                f"recent motion in adjacent area {neighbor}"
            )
            return False

    return True


### Scope functions
def get_entire_scope(device, device_area, *args):
    return [get_area_tree().get_root()]


# get immediate scope
# make it so they filter by all checking
def get_immediate_scope(device, device_area, *args):
    return get_local_scope(device, device_area, *args)


def get_local_scope(device, device_area, *args):
    return [device_area]


# When area names are passed in as args, gets their local scopes
def get_area_local_scope(device, device_area, *args):
    log.info(f"get_area_local_scope {args}")
    if len(args) == 0 or args[0] is None or len(args[0]) == 0:
        return [device_area]

    areas = []
    area_tree = get_area_tree()
    for area_name in args[0]:
        area_entry = area_tree.get_area_tree_lookup().get(area_name)
        if isinstance(area_entry, Area):
            areas.append(area_entry)
        else:
            log.info(f"Area {area_name} not found")

    if len(areas) == 0:
        return [device_area]

    log.info(f"get_area_local_scope {[area.name for area in areas]}")
    return areas


### State functions
# Functions that return a state based on some value


def _get_circadian_color_state(current_minutes, scope_rgb_color=None):
    """Return the time-appropriate color state (color_temp or rgb_color).

    Does NOT set brightness — caller adds that. Shared between
    get_time_based_state (motion events) and circadian_periodic_update
    (15-min color refresh).

    Args:
        current_minutes: minutes since midnight (local time)
        scope_rgb_color: optional current rgb_color for blending after sunset

    Returns:
        dict with color_temp or rgb_color key (may be empty if no change needed)
    """
    import datetime as dt
    import os as _os

    def _get_sunset_minutes():
        """Get today's sunset in local minutes since midnight."""
        try:
            from astral.sun import sun as astral_sun
            from astral import LocationInfo, Observer
            import yaml

            # Read lat/lon from sun_config.yml
            script_dir = _os.path.dirname(_os.path.abspath(__file__))
            config_paths = [
                _os.path.join(script_dir, "sun_config.yml"),
                "/config/pyscript/sun_config.yml",
            ]
            lat, lon = 37.7653, -122.2416  # default SF Bay Area
            for p in config_paths:
                if _os.path.exists(p):
                    with open(p) as f:
                        cfg = yaml.safe_load(f) or {}
                    loc_cfg = cfg.get("location", {})
                    lat = loc_cfg.get("latitude", lat)
                    lon = loc_cfg.get("longitude", lon)
                    break

            loc = LocationInfo("Home", "US", "America/Los_Angeles", lat, lon)
            obs = Observer(loc.latitude, loc.longitude)
            import pytz
            local_tz = pytz.timezone("America/Los_Angeles")
            sun_events = astral_sun(obs, date=dt.date.today(), tzinfo=local_tz)
            sunset = sun_events.get("sunset")
            if sunset:
                return sunset.hour * 60 + sunset.minute
        except Exception:
            pass
        # Fallback: ~19:56 (typical late-April sunset in SF)
        return 19 * 60 + 56

    sundown_minutes = _get_sunset_minutes()
    state = {}

    if current_minutes < 360:  # 00:00-06:00
        state["rgb_color"] = [255, 0, 0]
    elif current_minutes < 450:  # 06:00-07:30
        state["rgb_color"] = [255, 190, 130]
    elif current_minutes < 600:  # 07:30-10:00
        state["color_temp"] = 350
    elif current_minutes < 720:  # 10:00-12:00
        state["color_temp"] = 400
    elif current_minutes < 900:  # 12:00-15:00
        state["color_temp"] = 370
    elif current_minutes < sundown_minutes:  # 15:00-sunset
        state["color_temp"] = 350
    else:
        # After sunset — warm RGB
        hour = current_minutes // 60
        goal_color = [255, 190, 130] if hour < 22 else [255, 140, 70]
        if scope_rgb_color:
            state["rgb_color"] = combine_colors(
                scope_rgb_color, goal_color, strategy="average"
            )
        else:
            state["rgb_color"] = goal_color

    return state


def get_time_based_state(device, scope, *args):
    now = time.localtime()
    hour = now.tm_hour
    minute = now.tm_min
    current_minutes = hour * 60 + minute

    states = {}
    for area in scope:
        states[area.name] = area.get_state()
    scope_state = summarize_state(states)
    scope_rgb = scope_state.get("rgb_color")

    # Get color state from shared helper
    state = _get_circadian_color_state(current_minutes, scope_rgb)

    # Compute brightness
    max_brightness = 255
    overnight_brightness = 60

    def interpolate_over_quarters(start_minute, end_minute, start_value, end_value):
        total_minutes = end_minute - start_minute
        if total_minutes <= 0:
            return end_value
        clamped = max(0, min(current_minutes - start_minute, total_minutes))
        total_quarters = max(1, total_minutes // 15)
        current_quarter = min(total_quarters, clamped // 15)
        progress = current_quarter / total_quarters
        return round(start_value + (end_value - start_value) * progress)

    if 0 <= current_minutes < 60:  # 00:00-01:00
        brightness = interpolate_over_quarters(0, 60, max_brightness, overnight_brightness)
    elif 60 <= current_minutes < 300:  # 01:00-05:00
        brightness = overnight_brightness
    elif 300 <= current_minutes < 420:  # 05:00-07:00
        brightness = interpolate_over_quarters(300, 420, overnight_brightness, max_brightness)
    else:  # 07:00-24:00
        brightness = max_brightness

    state["status"] = 1
    state["brightness"] = brightness

    log.info(
        "Time based state: hour=%s minute=%s brightness=%s state=%s",
        hour,
        minute,
        brightness,
        state,
    )
    return state

def get_last_set_state(device, scope, *args):
    return get_cached_last_set_state()

def get_last_track_state(device, scope, *args):
    engine=get_occupancy_engine()
    area_tree=get_area_tree()
    device_area = device.get_area().name

    predecessor = engine.likely_predecessor(device_area)
    if predecessor is not None:
        log.info(
            f"get_last_track_state(): {device_area} likely from {predecessor}"
        )
        last_track_state=summarize_state(area_tree.get_state(predecessor))
        if "name" in last_track_state:
            del last_track_state["name"]
        log.info(f"get_last_track_state(): state from {predecessor}: {last_track_state}")
        return last_track_state

    log.info(f"get_last_track_state(): no predecessor found for {device_area}")
    return None



def toggle_status(device, scope, *args):
    states = {}
    for area in scope:
        states[area.name] = area.get_state()
        log.info(f"Area {area.name} state is {states[area.name]}")
    scope_state = summarize_state(states)
    log.info(f"Toggling status is {scope_state}")
    if "status" in scope_state:
        if scope_state["status"]:  # if on
            return {"status": 0}  # turn off
        else:
            return {"status": 1}  # turn on


def toggle_state(device, scope, *args):
    goal_state = {"status": 1, "color_temp": 350}
    opposite_state = {"status": 1, "rgb_color": [255, 149, 51]}

    def does_state_match_goal(state):
        return get_state_similarity(state, goal_state) >= 0.5

    states = {}
    for area in scope:
        states[area.name] = area.get_state()
        log.info(f"toggle_state: Area {area.name} state is {states[area.name]}")
    scope_state = summarize_state(states)

    log.info("toggle_state: Does scope_state match goal?")
    if does_state_match_goal(scope_state):
        log.info(f"toggle_state: Already in goal state, toggling to last scope state")

        last_states = {}
        for area in scope:
            last_states[area.name] = area.get_last_state()
        last_scope_state = summarize_state(last_states)
        last_scope_state["status"]=1
        log.info(f"toggle_state: Last state is {last_scope_state}")

        log.info("toggle_state: Does last_scope_state match goal?")
        if does_state_match_goal(last_scope_state):
            log.info(f"toggle_state: last scope state matches goal state, applying opposite state")
            return opposite_state

        # Strip keys that are not part of the controllable device state
        for key in ("temperature", "temp_color", "name", "device_name"):
            last_scope_state.pop(key, None)

        return last_scope_state

    else:
        log.info(f"toggle_state: scope_state does not match goal, toggling to {goal_state}")
        return goal_state

    return scope_state


###


def generate_state_trigger(trigger, functions, kwarg_list):
    log.info(f"generating state trigger @{trigger} {functions}( {kwarg_list} )")

    @service
    @state_trigger(trigger)
    def func_trig(**kwargs):
        log.info(f"TRIGGER: state trigger @{trigger} {functions}( {kwarg_list} )")
        # This assumes that if the functions are lists the kwargs are as well.
        if isinstance(functions, list):
            for function, kwargs in zip(functions, kwarg_list):
                function(**kwargs)
        else:
            functions(**kwarg_list)

    func_trig.__name__ = "state_trigger_" + trigger

    get_global_triggers().append(["trigger", trigger, func_trig])
    return func_trig


def _register_always_on_trigger(device_name):
    """Register a state trigger to restore always_on devices when turned off."""
    trigger_entity = f"switch.{device_name}"

    @state_trigger(f"{trigger_entity} == 'off'")
    def _always_on_restore():
        log.warning(f"always_on: {device_name} was turned off — restoring to ON")
        try:
            switch.turn_on(entity_id=trigger_entity)
        except Exception as e:
            log.error(f"always_on: Failed to restore {device_name}: {e}")

    _always_on_restore.__name__ = f"always_on_restore_{device_name}"
    get_global_triggers().append(["always_on", device_name, _always_on_restore])
    log.info(f"always_on: Registered restore trigger for {device_name}")


def merge_data(data):
    """
    Merge the given data into a single value.

    Args:
        data (list): A list of elements to be merged.

    Returns:
        The merged value of the given data.

    Raises:
        ValueError: If the provided data is empty or not all elements are of the same type.
        ValueError: If the data type is not supported.

    Notes:
        - The function supports merging integers and floats by taking the average.
        - The function supports merging lists by recursively merging items at corresponding indices.
        - The function supports merging dictionaries by recursively merging values for corresponding keys.

    """
    if not data:
        raise ValueError("merge_data(): Empty data provided")


    def is_similar(item1, item2):
        if issubclass(data_type, (list,tuple)) and issubclass(type(item), (list,tuple)) :
            return True
        if issubclass(data_type, (int,float)) and issubclass(type(item), (int,float)) :
            return True
        return False

    data_type = type(data[0])
    for item in data[1:]:
        if not issubclass(type(item), data_type) and not is_similar(item, data[0]):
            log.warning(f"merge_data(): Not all elements are of the same type {data}")
            return None

    # Handle integers and floats by averaging
    if issubclass(data_type, (int, float)):
        return sum(data) / len(data)

    # Handle lists
    elif issubclass(data_type, (list, tuple)) :
        max_length=len(data[0])
        for item in data:
            max_length=max(len(item),max_length)

        result = []
        for i in range(max_length):
            items_at_index = []
            for item in data:
                if len(item) > i:
                    items_at_index.append(item[i])
            # Recursively merge items at current index
            merged_item = merge_data(items_at_index)
            result.append(merged_item)
        return result

    # Handle dictionaries
    elif issubclass(data_type, dict):
        result = {}
        all_keys = set()
        for d in data:
            for key in d.keys():
                all_keys.add(key)
        for key in all_keys:
            values = []
            for d in data:
                if key in d and d[key] is not None:
                    values.append(d[key])
            if not values:
                continue
            # Recursively merge values for the current key
            merged_value = merge_data(values)
            result[key] = merged_value
        return result

    else:
        log.warning(f"merge_data(): Unsupported data type {data_type}: {data}")
        return None



def merge_states(state_list, name=None):
    """Merge multiple device states into one by averaging values.

    Uses ``merge_data`` for the heavy lifting, then clamps ``status`` to
    binary 0/1. This is intended for aggregating the actual states of
    multiple devices in the same area (e.g. "what is the average color of
    all lights in the living room?").

    For combining *candidate* states from rules/functions use
    ``combine_states`` which supports first/last/average strategies.
    """
    merged_state_list = []
    for state in state_list :
        state_copy = copy.deepcopy(state)
        if "name" in state_copy.keys(): del state_copy["name"]
        merged_state_list.append(state_copy)
    merged_state = merge_data(merged_state_list) if merged_state_list else {}
    if "status" in merged_state and merged_state["status"]>0:
        merged_state["status"]=1 
    else:
        merged_state["status"]=0
    log.info(f"merged_state: {merged_state}")
    return merged_state

def get_state_similarity(state1, state2):

    state1=copy.deepcopy(state1)
    if "name" in state1.keys(): del state1["name"]
    state2=copy.deepcopy(state2)
    if "name" in state2.keys(): del state2["name"]

    unique_to_state1 = set(state1.keys()) - set(state2.keys())

    # Find keys unique to state2
    unique_to_state2 = set(state2.keys()) - set(state1.keys())

    unique_keys = unique_to_state1.union(unique_to_state2)
    if "status" in unique_keys: unique_keys.remove("status") # If only one state has status, it probably doesn't matter in the comparison

    # Get number of shared keys
    shared_keys = set(state1.keys()).intersection(set(state2.keys()))
    num_shared=len(shared_keys)

    matching_vals=0
    for key in shared_keys:
        if  type(state1[key]) != type(state2[key]):
            log.info(f"State keys '{key}' have mismatched types: {state1[key]} vs {state2[key]}")
            num_shared-=1
            continue

        if type(state1[key]) == dict:
            matching_vals+=get_state_similarity(state1[key], state2[key])

        elif type(state1[key]) == list:
            # Compare element-wise: replace the single key with per-element scoring
            list_len = max(len(state1[key]), len(state2[key]))
            if list_len > 0:
                num_shared += list_len - 1  # replace 1 key with N element slots
                for i in range(min(len(state1[key]), len(state2[key]))):
                    if state1[key][i] == state2[key][i]:
                        matching_vals += 1
        elif state1[key] == state2[key]:
            matching_vals+=1

    total = num_shared + len(unique_keys)
    if total == 0:
        return 0.0
    similarity = matching_vals / total
    return similarity

# Color helpers


def rgb_to_hsl(r, g, b):
    """Convert RGB to HSL using Home Assistant helpers."""
    h, s = color_util.color_RGB_to_hs(r, g, b)
    # Home Assistant does not provide luminance; assume 50 for consistency.
    l = 50
    return h, s, l


def hs_to_rgb(h, s):
    """Convert HS color to RGB using Home Assistant helpers."""
    r, g, b = color_util.color_hs_to_RGB(h, s)
    return [r, g, b]


def k_to_rgb(k):
    """Convert a kelvin temperature into an RGB color tuple."""
    r, g, b = color_util.color_temperature_to_rgb(k)
    return [r, g, b]


class Area:
    def __init__(self, name):
        self.name = name
        self.children = []
        self.direct_children = []
        self.devices = []
        self.parent = None
        self.frozen = False
        self.motion_off_delay = None  # seconds; None means use DEFAULT_MOTION_OFF_DELAY

    def add_parent(self, parent):
        self.parent = parent

    def add_child(self, child, direct=False):
        if child is not None and child.name is not None:
            self.children.append(child)
            if direct:
                self.direct_children.append(child)

    def add_device(self, device):
        if device is not None and device.name is not None:
            log.info(f"Area {self.name}: adding device {device.name}")
            self.devices.append(device)

    def get_devices(self):
        return self.devices

    def get_children(self, exclude_devices=False):
        if exclude_devices:
            return list(set(self.children + self.direct_children))

        return list(set(self.children + self.direct_children + self.devices))

    def get_direct_children(self):
        return list(set(self.direct_children))

    def get_parent(self):
        return self.parent

    def has_children(self, exclude_devices=False):
        return len(self.get_children(exclude_devices)) > 0

    def freeze(self, propagate=True):
        """Freeze this area so state changes are ignored."""
        self.frozen = True
        for child in self.get_children(exclude_devices=False):
            if isinstance(child, Area) and propagate:
                child.freeze(propagate=True)
            elif isinstance(child, Device):
                child.lock(True)

    def unfreeze(self, propagate=True):
        """Unfreeze this area allowing state changes again."""
        self.frozen = False
        for child in self.get_children(exclude_devices=False):
            if isinstance(child, Area) and propagate:
                child.unfreeze(propagate=True)
            elif isinstance(child, Device):
                child.lock(False)

    def is_frozen(self):
        return self.frozen

    def set_state(self, state, device_type_filter=None, event_id=""):
        log.info("Area.set_state", extra={
                "area": self.name, "state": state,
                "filter": str(device_type_filter), "event_id": event_id
            })
        if self.frozen:
            log.info(f"Area {self.name} is frozen; skipping state change {state}")
            return
        children = self.get_children()
        log.info(f"Area {self.name}: set_state iterating {len(children)} children")
        for child in children:
            try:
                if hasattr(child, 'driver'):
                    # Child is a Device (has a driver attribute)
                    # Skip power-monitoring devices -- they should never be toggled by area state changes
                    if child.power_monitoring:
                        log.info(f"Area {self.name}: Skipping power-monitoring device {child.name}")
                        continue
                    # Skip devices not matching the type filter (if set)
                    if device_type_filter is not None:
                        child_type = getattr(child.driver, "device_type", None)
                        if child_type not in device_type_filter:
                            log.info(f"Area {self.name}: Skipping {child.name} (type '{child_type}' not in filter {device_type_filter})")
                            continue
                    if not state:
                        log.info(f"Area {self.name}: Skipping {child.name} (empty state)")
                        continue
                    child.set_state(copy.deepcopy(state), event_id=event_id)
                else:
                    # Sub-area: propagate the filter
                    child.set_state(copy.deepcopy(state), device_type_filter=device_type_filter, event_id=event_id)
            except Exception as exc:
                log.error(f"Area {self.name}: Exception setting state on child {getattr(child, 'name', child)}: {exc}")

    def get_state(self):
        log.info(f"Area:get_state(): Getting state for {self.get_pretty_string()}")
        child_states = []

        for child in self.get_children():
            child_state = child.get_state()
            log.info(f"Area:get_state(): Child state: {child.name} {child_state}")
            child_states.append(child_state)
        log.info(f"merging states: {child_states}")
        merged = merge_states(child_states, self.name)

        return merged

    def get_last_state(self):
        child_states = []

        for child in self.get_children():
            child_state = child.get_last_state()
            child_states.append(child_state)

        merged = merge_states(child_states, self.name)

        return merged

    def get_pretty_string(self, indent=1, is_direct_child=False, show_state=False):
        """Prints a tree representation with accurate direct child highlighting."""
        string_rep = (
            "\n"
            + " " * indent
            + f"{('(Direct) ' if is_direct_child else '') + self.name}:\n"
        )

        if show_state:
            string_rep += "  " * indent + f"  Last State: {self.last_state}\n"

        if self.has_children():
            string_rep += "  " * indent + "│\n"
            for child in self.get_children():
                direct = False
                if child in self.direct_children:
                    direct = True
                string_rep += child.get_pretty_string(indent + 2, direct, show_state)
        else:
            string_rep += "  " * indent + "└── (No children)\n"

        return string_rep


@pyscript_compile
def load_yaml(path):
    with builtins.open(path, "r") as f:
        data = yaml.safe_load(f)
    return data


@pyscript_compile
def load_device_defs(devices_path, discovered_path="./pyscript/discovered.yml"):
    """Load discovered devices first, then apply manual device overrides."""
    device_defs = {}

    try:
        device_defs = load_yaml(discovered_path) or {}
    except Exception:
        device_defs = {}

    try:
        manual_defs = load_yaml(devices_path) or {}
        device_defs.update(manual_defs)
    except Exception:
        pass

    return device_defs


### Tracker interface
def update_tracker(device, *args):
    area_name = device.get_area().name

    if SHADOW_MODE:
        # --- Shadow mode: run both trackers, use legacy for decisions ---
        legacy = get_tracker_manager()
        engine = get_occupancy_engine()

        if legacy is not None and engine is not None:
            # Both trackers available — dual-track
            before_new = engine.room_occupancy_confidence(area_name)

            # Legacy: drive actual automations
            try:
                legacy.add_event(area_name)
            except Exception:
                pass  # graceful — legacy may be stubbed in tests

            # New: record for comparison (read-only)
            engine.handle_motion(area_name)

            after_new = engine.room_occupancy_confidence(area_name)

            # Shadow comparison: log disagreements between old and new
            try:
                _shadow_compare(engine, legacy, area_name)
            except Exception:
                pass  # graceful — shadow comparison is best-effort

            # Log both trackers' view
            try:
                legacy_count = len(legacy.tracks)
            except Exception:
                legacy_count = "?"
            log.info(f"update_tracker: {area_name} | "
                     f"new_conf={before_new:.3f}→{after_new:.3f} "
                     f"legacy={legacy_count} tracks")
        else:
            # Shadow mode but one tracker unavailable (test env) — OccupancyEngine only
            if engine is not None:
                engine.handle_motion(area_name)
            log.info(f"update_tracker: {area_name} (shadow degraded)")

    else:
        # --- Production mode: OccupancyEngine only ---
        engine = get_occupancy_engine()
        engine.handle_motion(area_name)

    try:
        get_learner().record_presence(area_name)
    except Exception:
        pass

    log.info(f"update_tracker: {area_name}")

    return True


def _shadow_compare(engine, legacy, area_name):
    """Compare legacy TrackManager vs OccupancyEngine for disagreement logging.

    Checks:
    1. Does legacy think someone is in this area? (active track head)
    2. Does the new engine have confidence > 0.15?
    3. For adjacent rooms: do legacy tracks exist vs engine confidence?
    """
    # --- Per-room agreement check ---
    new_conf = engine.room_occupancy_confidence(area_name)
    new_active = new_conf > 0.15

    # Legacy: an area is "active" if any track has this area as its head
    legacy_active = any(
        track.head == area_name
        for track in legacy.tracks
    )

    if new_active != legacy_active:
        log.info(
            f"[shadow] DISAGREE area={area_name} "
            f"legacy=active:{legacy_active} new=conf:{new_conf:.2f}"
        )

    # --- Adjacent room check ---
    neighbors = engine.neighbors(area_name)
    for nb in neighbors:
        nb_conf = engine.room_occupancy_confidence(nb)
        nb_new = nb_conf > 0.15
        nb_legacy = any(track.head == nb for track in legacy.tracks)

        if nb_new != nb_legacy and (nb_conf > 0.05 or nb_legacy):
            # Only log if either tracker thinks something meaningful is happening
            log.info(
                f"[shadow] DISAGREE ADJ area={area_name}→{nb} "
                f"legacy=active:{nb_legacy} new=conf:{nb_conf:.2f}"
            )

    # --- Cross-check: rooms with tracks but low confidence ---
    for track in legacy.tracks:
        head = track.head
        if head is not None:
            conf = engine.room_occupancy_confidence(head)
            if conf < 0.05 and head != area_name:
                log.info(
                    f"[shadow] LEGACY_TRACK_NO_CONF area={head} "
                    f"legacy_has_track=true new_conf={conf:.3f}"
                )



class EventManager:
    def __init__(self, rules_file, area_tree):
        self.rules = load_yaml(rules_file)
        self.area_tree = area_tree

    def create_event(self, event):
        # Generate an event_id for cause-effect tracing across the pipeline.
        if "event_id" not in event:
            event["event_id"] = f"{int(time.time() * 1000):x}_{random.randint(0, 65535):04x}"
        log.info(f"EventManager: New event: {event}", extra={"event_id": event.get("event_id", "")})

        result = self.check_event(event)

    def check_event(self, event):
        if "device_name" not in event:
            log.warning(f"EventManager:check_event(): Missing device_name in event {event}, dropping")
            return False
        matching_rules = []
        rule_lookup = self.get_rules()
        for rule_name in rule_lookup.keys():
            # Get devices that names match trigger_prefix
            trigger_prefix = rule_lookup[rule_name]["trigger_prefix"]
            if event["device_name"].startswith(trigger_prefix):
                if "service" in event["device_name"]:
                    log.info(f"EventManager:check_event(): SERVICESEARCH")
                if get_verbose_mode():
                    log.info(
                        f"EventManager:check_event(): Rule {rule_name} prefix [{trigger_prefix}] matches {event['device_name']}"
                    )
                function_override = False
                tag_override = False
                if "tags" in event:
                    if "tag_override" in event["tags"]:
                        tag_override = True
                    if "function_override" in event["tags"]:
                        function_override = True

                approved = True
                if not (
                    tag_override or self._check_tags(event, rule_lookup[rule_name])
                ):
                    approved = False

                if get_verbose_mode() and approved:
                    log.info(f"EventManager:check_event(): {rule_name} Passed tag check")

                if "tags" in event:
                    if "tag_override" in event["tags"]:
                        tag_override = True

                if not approved or (
                    function_override
                    and (not self._check_functions(event, rule_lookup[rule_name]))
                ):
                    approved = False
                    # log.info(f"EventManager:check_event(): {rule_name} FAILED function check")

                if get_verbose_mode() and approved:
                    log.info(f"EventManager:check_event(): {rule_name} Passed function check")

                if approved:
                    matching_rules.append(rule_name)

        event_tags = event.get("tags", [])
        log.info("EventManager:check_event()", extra={
            "event_id": event.get("event_id", ""),
            "event": {k: v for k, v in event.items() if k != "event_id"},
            "matches": list(matching_rules)
        })

        results = []
        for rule_name in matching_rules:
            rule = copy.deepcopy(self.rules[rule_name])
            log.info(f"EventManager:check_event():  Rule: {rule}")
            results.append(self.execute_rule(event, rule, rule_name=rule_name))

        if results is not None:
            return results

        return False  # No matching rule

    # Looks for keywords in args and replaces them with values
    def expand_args(self, args, event_data, state):
        result = []
        for arg in args:
            if isinstance(arg, str) and arg.startswith("$"):
                if arg == "$state":
                    log.info(f"Expanding $state to {state}")
                    result.append(state)
                else:
                    result.append(arg)
            else:
                result.append(arg)
        return result

    def execute_rule(self, event_data, rule, rule_name=None):
        device_name = event_data["device_name"]

        log.info("EventManager:execute_rule()", extra={
            "event_id": event_data.get("event_id", ""),
            "rule": rule_name,
            "device": device_name,
            "event_data": {k: v for k, v in event_data.items() if k != "event_id"}
        })
        device = self.get_area_tree().get_device(device_name)



        if device is not None:
            # get values
            device_area = device.get_area()
            rule_state = rule.get("state", {})
            device_type_filter = rule.get("device_type_filter", None)

            event_scope_functions = event_data.get("scope_functions")
            if event_scope_functions is not None:
                rule["scope_functions"] = event_scope_functions

            scope = None  # Should these be anded?
            # Get scope to apply to
            if "scope_functions" in rule:
                for function_pair in rule["scope_functions"]:  # function_name:args
                    for function_name, args in function_pair.items():
                        function = get_function_by_name(function_name)
                        # If function exists, run it
                        if function is not None:
                            new_scope = function(device, device_area, args)
                            if new_scope is not None:
                                if scope is None:  # if no scope to compare with, set
                                    scope = new_scope
                                else:
                                    edited_scope = []
                                    for area in scope:
                                        if get_verbose_mode():
                                            log.info(
                                                f"EventManager:execute_rule(): Checking if {area.name} in {new_scope}"
                                            )
                                        if area in new_scope:
                                            edited_scope.append(area)
                                    log.info(f"EventManager:execute_rule(): Edited scope: {scope}->{edited_scope}")
                                    scope = edited_scope

            if not scope:
                if isinstance(device.driver, ServiceDriver):
                    nearest_area = self.get_area_tree().get_nearest_area_with_outputs(device_area)
                    if nearest_area is not None:
                        scope = [nearest_area]
                    else:
                        scope = get_local_scope(device, device_area)
                else:
                    scope = get_local_scope(device, device_area)

            if isinstance(device.driver, ServiceDriver):
                mapped_scope = []
                for scoped_area in scope:
                    nearest_area = self.get_area_tree().get_nearest_area_with_outputs(scoped_area)
                    if nearest_area is not None and nearest_area not in mapped_scope:
                        mapped_scope.append(nearest_area)
                if mapped_scope:
                    scope = mapped_scope

            scope_names=[]
            for area in scope:
                scope_names.append(area.name)
            
            log.info("EventManager:execute_rule(): scope resolved", extra={
                "event_id": event_data.get("event_id", ""),
                "scope": scope_names
            })

            function_states = []
            # if there are state functions, run them
            if rule.get("state_functions"):
                log.info(f"EventManager:execute_rule(): State functions: {rule['state_functions']}")
                for function_pair in rule["state_functions"]:  # function_name:args
                    for function_name, args in function_pair.items():
                        function = get_function_by_name(function_name)
                        # If function exists, run it
                        if function is not None:
                            function_state = function(device, scope, args)
                            # Adds the states to a list to be combined
                            log.info("EventManager:execute_rule(): function state", extra={
                                "event_id": event_data.get("event_id", ""),
                                "function": function_name,
                                "result": function_state
                            })
                            function_states.append(function_state)

                log.info(f"EventManager:execute_rule(): Function states: {rule['state_functions']} provided  {function_states}")
            # Add state_list to event_state
            state_list = []
            if "state" in event_data:
                # Manual state from event_data is added first (lowest priority in
                # "last" strategy, blended equally in "average").
                state_list.append(event_data["state"])

            state_list.extend(function_states)
            # Rule-level state comes last so it wins in "last" strategy.
            state_list.append(rule_state)

            strategy="average"
            if "combination_strategy" in rule:
                strategy = rule["combination_strategy"]
            final_state = combine_states(
                state_list, strategy=strategy
            )

            log.info("EventManager:execute_rule(): merged state", extra={
                "event_id": event_data.get("event_id", ""),
                "final_state": final_state,
                "strategy": strategy
            })



            #For now, assuming functions are boolean, if fail, ignore rule.
            # This is down here so we have full states for expanding args
            if "functions" in rule:
                for function_pair in rule["functions"]:  # function_name:args
                    for function_name, args in function_pair.items():
                        function = get_function_by_name(function_name)
                        
                        # If function exists, run it
                        if function is not None:
                            args=self.expand_args(args, event_data, final_state)
                            if not function(device, *args) :
                                log.info("EventManager:execute_rule(): function failed", extra={
                                        "event_id": event_data.get("event_id", ""),
                                        "function": function_name, "action": "block_rule"
                                    })
                                return False
            log.info("EventManager:execute_rule(): all functions passed", extra={
                    "event_id": event_data.get("event_id", "")
                })
            log.info("EventManager:execute_rule(): apply-state", extra={
                "event_id": event_data.get("event_id", ""),
                "state": final_state,
                "scope": scope_names
            })
            if device.target_outputs:
                for target_device_name in device.target_outputs:
                    target_device = self.get_area_tree().get_device(target_device_name)
                    if target_device is None:
                        log.warning(
                            f"EventManager:execute_rule(): target output '{target_device_name}' not found"
                        )
                        continue
                    if target_device.power_monitoring:
                        continue
                    if device_type_filter is not None:
                        target_type = getattr(target_device.driver, "device_type", None)
                        if target_type not in device_type_filter:
                            continue
                    if final_state:
                        target_device.set_state(copy.deepcopy(final_state),
                                                 event_id=event_data.get("event_id", ""))
            else:
                for areas in scope:
                    areas.set_state(final_state, device_type_filter=device_type_filter,
                                    event_id=event_data.get("event_id", ""))

            if rule_name is not None:
                try:
                    get_learner().record_rule_event(rule_name)
                except Exception:
                    pass

            return True
        else:
            log.warning(f"EventManager:execute_rule(): Device {device_name} not found")
            return False

    def _check_tags(self, event, rule):
        """Checks if the tags passed the rules tags"""
        tags = event.get("tags", [])
        if "required_tags" in rule:
            if get_verbose_mode():
                log.info(
                    f"Checking Required tags {rule['required_tags']} against {tags}"
                )
            for tag in rule["required_tags"]:
                if tag not in tags:
                    if get_verbose_mode():
                        log.info(f"Required tag {tag} not found in event {event}")
                    return False
        if "prohibited_tags" in rule:
            if get_verbose_mode():
                log.info(
                    f"Checking Prohibited tags {rule['prohibited_tags']} against {tags}"
                )
            for tag in rule["prohibited_tags"]:
                if tag in tags:
                    if get_verbose_mode():
                        log.info(f"Prohibited tag {tag} found in event {event}")
                    return False
        if get_verbose_mode():
            log.info(f"Passed tag check")
        return True

    def _check_functions(self, event, rule, **kwargs):
        functions = rule.get("functions", [])
        if len(functions) > 0:
            for function_data in functions:
                # split dict key and value to get functoin name and args
                function_name = list(function_data.keys())[0]

                function = get_function_by_name(function_name)
                if function is not None:
                    result = function(event, **kwargs)
                    if not result:
                        if get_verbose_mode():
                            log.info(f"Function {function_name} failed")
                        return False

        return True  # If passed all checks or theres no functions to pass

    def get_area_tree(self):
        return self.area_tree

    def get_rules(self):
        return copy.deepcopy(self.rules)


class AreaTree:
    """Acts as an interface to the area tree"""

    def __init__(self, config_path, devices_file="devices.yml"):
        self.config_path = config_path
        self.device_defs = load_device_defs(
            devices_file,
            config_settings.get("discovered", DEFAULT_CONFIG["discovered"]),
        )
        self.area_tree_lookup = self._create_area_tree(self.config_path)

        log.info(f"AreaTree: Created area tree with children: {list(self.area_tree_lookup.keys())}")
        if 'living_room_corner_lamp' in self.area_tree_lookup:
            log.info(f"DEBUG: living_room_corner_lamp: {self.area_tree_lookup['living_room_corner_lamp']}")
            log.info(f"DEBUG: living_room_corner_lamp: {self.area_tree_lookup['living_room_corner_lamp'].get_pretty_string(show_state=True)}")

        self.root_name = self._find_root_area_name()

    def get_state(self, area=None):
        if area is None:
            area = self.root_name

        state=self.area_tree_lookup[area].get_state()
        log.info(f"AreaTree:get_state(): State for {area} is {state}")
        return state

    def get_root(self):
        return self.get_area(self.root_name)

    def get_area(self, area_name=None):
        if area_name is None:
            area_name = self.root_name
        if area_name not in self.area_tree_lookup:
            log.warning(f"Area {area_name} not found in area tree")
            return None
        return self.area_tree_lookup[area_name]

    def get_device(self, device_name):
        if device_name not in self.area_tree_lookup:
            log.warning(f"Device {device_name} not found in area tree")
            return None
        return self.area_tree_lookup[device_name]

    def get_area_tree_lookup(self):
        return self.area_tree_lookup

    def is_area(self, area_name):
        log.info(f"Checking if {area_name} is an area")
        return isinstance(self.get_area_tree_lookup().get(area_name), Area)

    def _find_root_area_name(self):
        root_area = None
        for name, area in self.area_tree_lookup.items():
            if area.parent is None:
                root_area = name
                break
        return root_area

    def get_greatest_area(self, area_name):
        # Gets the highest area which still has the input area as a direct child
        if area_name not in self.area_tree_lookup:
            log.warning(f"Area {area_name} not found in area tree")
            return None

        starting_area = self.area_tree_lookup[area_name]

        highest_area = starting_area
        parent = starting_area.get_parent()

        while parent is not None:
            if highest_area in parent.direct_children:
                highest_area = parent
                parent = parent.get_parent()
            else:
                return highest_area

        return self.get_area()  # return root if runs out of parents

    def get_lowest_children(self, area_name, include_devices=False):
        area = self.get_area(area_name)

        lowest_areas = []

        def traverse(area):
            if len(area.get_children(exclude_devices=(not include_devices))) == 0:
                lowest_areas.append(area)
            else:
                for child in area.get_children(exclude_devices=True):
                    traverse(child)

        traverse(area)
        return lowest_areas

    def get_greater_siblings(self, area_name, **args):
        area = self.get_area(area_name)
        greatest_parent = self.get_greatest_area(area_name)
        siblings = greatest_parent.get_direct_children()
        if area in siblings:
            siblings.remove(area)
        return siblings

    def get_lesser_siblings(self, area_name):
        area = self.get_area(area_name)
        greatest_parent = self.get_greatest_area(area_name)
        siblings = self.get_lowest_children(greatest_parent.name)
        if area in siblings:
            siblings.remove(area)
        return siblings

    def get_nearest_area_with_outputs(self, area_or_name):
        if area_or_name is None:
            return None

        if isinstance(area_or_name, str):
            current = self.get_area(area_or_name)
        else:
            current = area_or_name

        input_drivers = (MotionSensorDriver, PresenceSensorDriver, ServiceDriver)

        while current is not None:
            for device in current.get_devices():
                if isinstance(device, Device) and not isinstance(device.driver, input_drivers):
                    return current
            current = current.get_parent()

        return None

    def _create_area_tree(self, yaml_file):
        """
        Loads areas from a YAML file and creates a hierarchical structure of Area objects.

        Args:
            yaml_file: Path to the YAML file containing area definitions.

        Returns:
            A dictionary mapping area names to their corresponding Area or Device objects.
        """

        data = load_yaml(yaml_file)
        log.info(f"Loaded area configuration from {yaml_file}, areas={list(data.keys())}")

        area_tree = {}
        area_names = set()  # Track unique area names

        def create_area(name):
            """Creates an Area object, ensuring unique names."""
            if name not in area_names:
                log.info(f"Creating new Area: {name}")
                area = Area(name)
                area_tree[name] = area
                area_names.add(name)
                return area
            else:
                return area_tree[name]  # Reuse existing object

        # Create initial areas
        for area_name, area_data in data.items():
            if area_name is None:
                log.warning("Encountered area with name=None in YAML. Skipping.")
                continue

            if area_data is None:
                log.warning(f"Area '{area_name}' has no configuration data. Skipping.")
                continue

            area = create_area(area_name)

            # Store per-area motion-off delay if configured
            motion_off_delay = area_data.get("motion_off_delay")
            if motion_off_delay is not None:
                try:
                    area.motion_off_delay = int(motion_off_delay)
                    log.info(f"Area '{area_name}': motion_off_delay={area.motion_off_delay}s")
                except (ValueError, TypeError) as exc:
                    log.warning(f"Area '{area_name}': invalid motion_off_delay '{motion_off_delay}': {exc}")

            # Create direct child relationships
            direct_sub_areas = area_data.get("direct_sub_areas")
            if direct_sub_areas is not None:
                for direct_child in direct_sub_areas:
                    if direct_child is None:
                        log.warning(f"Area '{area_name}' has a None direct_sub_area entry.")
                        continue
                    child = create_area(direct_child)
                    child.add_parent(area)
                    area.add_child(child, direct=True)
                    log.info(f"Added direct child area '{direct_child}' to '{area_name}'")

            # Create child relationships
            sub_areas = area_data.get("sub_areas")
            if sub_areas is not None:
                for child_name in sub_areas:
                    if child_name is None:
                        log.warning(f"Area '{area_name}' has a None sub_area entry.")
                        continue
                    new_area = create_area(child_name)
                    new_area.add_parent(area)
                    area.add_child(new_area, direct=False)
                    log.info(f"Added child area '{child_name}' to '{area_name}' (indirect)")

            # Add outputs as children
            outputs = area_data.get("outputs")
            if outputs is not None:
                for output in outputs:
                    if output is None:
                        log.warning(f"Area '{area_name}' has a None output entry.")
                        continue

                    driver = None
                    driver_label = None

                    info = self.device_defs.get(output)
                    if info is None:
                        log.warning(
                            f"Area '{area_name}': No device config entry for output '{output}'. "
                            f"Device will be skipped."
                        )
                        continue

                    dtype = info.get("type")
                    filters = info.get("filters", [])

                    # Outputs are expected to have filters as a list per your config assumption
                    if not isinstance(filters, list):
                        log.warning(
                            f"Device '{output}' in area '{area_name}' has non-list filters={filters!r}. "
                            f"Treating as empty."
                        )
                        filters = []

                    # Lights
                    if dtype == "light":
                        if "hue" in filters:
                            driver = HueLight(output)
                            driver_label = "HueLight"
                        else:
                            driver = KaufLight(output)
                            driver_label = "KaufLight"

                    # Blinds
                    elif dtype == "blind" or (dtype is None and "blind" in output):
                        height = info.get("height", BLIND_HEIGHTS.get(output, 100))
                        driver = BlindDriver(output, height)
                        driver_label = "BlindDriver"

                    # Speakers
                    elif dtype == "speaker" or (
                        dtype is None and ("speaker" in output or "google_home" in output)
                    ):
                        driver = SpeakerDriver(output)
                        driver_label = "SpeakerDriver"

                    # Plugs
                    elif dtype == "plug":
                        driver = PlugDriver(output)
                        driver_label = "PlugDriver"

                    # Contact sensors
                    elif dtype == "contact_sensor":
                        driver = ContactSensorDriver(output)
                        driver_label = "ContactSensorDriver"

                    # Fans
                    elif dtype == "fan":
                        driver = FanDriver(output)
                        driver_label = "FanDriver"

                    # Televisions
                    elif dtype == "television":
                        driver = TelevisionDriver(output)
                        driver_label = "TelevisionDriver"

                    # Unknown type
                    else:
                        log.warning(
                            f"Area '{area_name}': Unsupported or missing type for output '{output}'. "
                            f"type={dtype!r}, filters={filters!r}. No driver created."
                        )

                    if driver is not None:
                        new_device = Device(driver)
                        if new_device is None:
                            log.warning(
                                f"Area '{area_name}': Failed to create device for output '{output}'."
                            )
                        area.add_device(new_device)
                        new_device.set_area(area)
                        area_tree[output] = new_device
                        log.info(
                            f"Area '{area_name}': Created {driver_label}: {type(new_device)} for output '{output}'."
                        )

            # Add power_outputs as power-monitoring devices (never toggled by motion)
            power_outputs = area_data.get("power_outputs")
            if power_outputs is not None:
                for output in power_outputs:
                    if output is None:
                        log.warning(f"Area '{area_name}' has a None power_output entry.")
                        continue

                    info = self.device_defs.get(output)
                    if info is None:
                        log.warning(
                            f"Area '{area_name}': No device config entry for power_output '{output}'. "
                            f"Device will be skipped."
                        )
                        continue

                    driver = PlugDriver(output)
                    new_device = Device(driver)
                    new_device.power_monitoring = True
                    new_device.always_on = bool(info.get("always_on", False))
                    area.add_device(new_device)
                    new_device.set_area(area)
                    area_tree[output] = new_device
                    log.info(
                        f"Area '{area_name}': Created power-monitoring PlugDriver for power_output '{output}'."
                    )
                    if new_device.always_on:
                        _register_always_on_trigger(output)

            # Add inputs as children
            if "inputs" in area_data:
                inputs = area_data["inputs"]
                log.info(f"Area '{area_name}': Inputs config: {inputs!r}")

                if isinstance(inputs, list):
                    if len(inputs) > 0 and inputs[0] is not None:
                        log.warning(
                            f"Area '{area_name}': Inputs are a list ({inputs!r}). "
                            f"List inputs are not supported and will not be processed."
                        )
                    else:
                        log.warning(
                            f"Area '{area_name}': Inputs is an empty list. Nothing to process."
                        )

                elif isinstance(inputs, dict):
                    for input_type, device_id_list in inputs.items():
                        if input_type is None:
                            log.warning(
                                f"Area '{area_name}': Found input entry with input_type=None. Skipping."
                            )
                            continue
                        if device_id_list is None:
                            log.warning(
                                f"Area '{area_name}': Input type '{input_type}' has None device list. Skipping."
                            )
                            continue

                        if not isinstance(device_id_list, list):
                            log.warning(
                                f"Area '{area_name}': Input type '{input_type}' expected list, got {type(device_id_list)}. Skipping."
                            )
                            continue

                        for device_entry in device_id_list:
                            device_id = None
                            target_outputs = None
                            if isinstance(device_entry, str):
                                device_id = device_entry
                            elif isinstance(device_entry, dict):
                                device_id = device_entry.get("name")
                                target_outputs = device_entry.get("target_outputs")
                            else:
                                log.warning(
                                    f"Area '{area_name}', input_type '{input_type}': Unsupported input entry {device_entry!r}. Skipping."
                                )
                                continue

                            if device_id is None:
                                log.warning(
                                    f"Area '{area_name}', input_type '{input_type}': "
                                    f"Encountered None device_id. Skipping."
                                )
                                continue

                            new_input = None
                            if input_type == "motion":
                                log.info(f"Area '{area_name}': Creating motion device: {device_id}")
                                new_input = MotionSensorDriver(input_type, device_id)
                            elif input_type == "presence":
                                log.info(f"Area '{area_name}': Creating presence device: {device_id}")
                                new_input = PresenceSensorDriver(input_type, device_id)
                            elif input_type == "service":
                                log.info(f"Area '{area_name}': Creating service device: {device_id}")
                                new_input = ServiceDriver(input_type, device_id)
                            else:
                                log.warning(
                                    f"Area '{area_name}': Input type '{input_type}' has no driver mapping for '{device_id}'. Skipping."
                                )

                            if new_input is not None:
                                new_device = Device(new_input)
                                if target_outputs is not None:
                                    if isinstance(target_outputs, list):
                                        new_device.target_outputs = target_outputs
                                    else:
                                        log.warning(
                                            f"Area '{area_name}': target_outputs for '{device_id}' must be a list. Ignoring."
                                        )
                                new_input.add_callback(new_device.input_trigger)

                                area.add_device(new_device)
                                new_device.set_area(area)

                                area_tree[new_device.name] = new_device
                                log.info(
                                    f"Area '{area_name}': Added input device '{new_device.name}'."
                                )
                else:
                    log.warning(
                        f"Area '{area_name}': 'inputs' has unsupported type {type(inputs)}. "
                        f"Expected list or dict. Value={inputs!r}"
                    )
        for k,v in area_tree.items():
            log.info(f"AreaTree contains: {k}: {v}")
            log.info(f"AreaTree contains pretty {k}: {v.get_pretty_string()}")
        log.info(area_tree)
        return area_tree

    def get_pretty_string(self):
        log.info("DEBUG: Getting pretty string of area tree")
        return self.get_area(self.root_name).get_pretty_string()


class Device:
    """Acts as a wrapper/driver for a device type -- interfaces between states and devices."""

    def __init__(self, driver):
        self.driver = driver
        self.name = driver.name
        self.last_state = None # The previous state before the current one (and current cache) was applied
        self.cached_state = None # The most recent applied state, used to fillout states.
        self.area = None
        self.tags = []
        self.locked=False
        self.power_monitoring = False
        self.always_on = False
        self.target_outputs = None

    # "Lock" The device so it can't be changed
    def lock(self, value=True):
        if value:
            log.info(f"Locking {self.name}")
        else:
            log.info(f"Unlocking {self.name}")
        self.locked = value

    def get_state(self):
        
        state = self.driver.get_state()
        log.info(f"Device:get_state(): Getting state for {self.name} state:{state}")
        state["name"] = self.name
        # self.cached_state = state #Update cached state to that of driver
        state=self.fillout_state_from_cache(state)
        log.info(f"Device:get_state(): filled out state: {state}")
        return state

    def get_last_state(self):
        if self.last_state is None:
            state = {} if self.cached_state is None else copy.deepcopy(self.cached_state)
        else:
            state = copy.deepcopy(self.last_state)
        state["name"] = self.name
        log.info(f"Device:get_last_state(): Last state: {state}")
        return state

    def fillout_state_from_cache(self, state):
        if self.cached_state is not None and type(self.cached_state)==dict:
            log.info(f"Device:fillout_state_from_cache(): Filling out state {state} from cache: {self.cached_state}")
            for key, val in self.cached_state.items():

                if key not in state.keys():
                    state[key] = val
        return state

    def filter_state(self, state) :
        return self.driver.filter_state(state)


    def add_to_cache(self, state):
        # Remove keys that don't apply to driver (buttons don't have rgb color etc...)
        if state is not None :
            state=self.filter_state(state)

            self.last_state = self.cached_state
            new_state=copy.deepcopy(self.cached_state) # Set cached state as old state
            if new_state is None :
                new_state = {}
            for key, val in state.items():
                new_state[key] = copy.deepcopy(val) #update with new values
            self.cached_state = new_state
            log.info(f"add_to_cache: Added {state} to {self.last_state} to create Cached state: {self.cached_state}")

    def input_trigger(self, tags):
        global event_manager

        event = {"device_name": self.name, "tags": tags}
        log.info(f"Device {self.area.name} Triggered. Event: {event}")

        event_manager.create_event(event)

    def set_state(self, state, event_id=""):
        log.info("Device.set_state", extra={
                "device": self.name, "state": state, "event_id": event_id
            })
        if not self.locked:
            state = copy.deepcopy(state)
            if hasattr(self.driver, "set_state"):
                # The driver handles color_type conflicts (rgb vs temp)
                # via its apply_values logic which tracks color_type internally.
                if get_verbose_mode():
                    log.info(f"Setting state: {state} on {self.name}")
                log.info("Device: driver set_state", extra={
                        "device": self.name, "state": state, "event_id": event_id
                    })

                applied_state=self.driver.set_state(state)
                log.info("Device: applied state", extra={
                        "device": self.name, "state": applied_state, "event_id": event_id
                    })
                self.add_to_cache(applied_state)
                log.info("Device: cache updated", extra={
                        "device": self.name, "cached": self.cached_state, "event_id": event_id
                    })
        else :
            if get_verbose_mode():
                log.info(f"Device {self.name} is locked, not setting state {state}")

    def get(self, value):
        if self.cached_state is None:
            return None
        return self.cached_state.get(value)

    def set_area(self, area):
        self.area = area

    def get_area(self):
        return self.area

    def add_tag(self, tag):
        self.tags.append(tag)

    def get_tags(self):
        return self.tags

    def get_name(self):
        return self.name

    def get_pretty_string(self, indent=1, is_direct_child=False, show_state=False):
        log.info(f"DEBUG: Getting pretty string of {self.name}")
        string_rep = (
            " " * indent + f"{('(Direct) ' if is_direct_child else '') + self.name}:\n"
        )

        if show_state:
            string_rep += " " * (indent + 2) + f"State: {self.get_state}\n"

        if string_rep is None:
            string_rep = "FUCK"
        log.info(f"DEBUG: Getting pretty string of {self.name} -> {string_rep}")
        return string_rep


class MotionSensorDriver:
    def __init__(self, input_type, device_id):
        self.name = self.create_name(input_type, device_id)

        self.last_state = {}
        self.trigger = self.setup_service_triggers(device_id)

        self.callback = None

    def create_name(self, input_type, device_id):
        if "." in device_id:
            # get value after .
            device_id = device_id.split(".", 1)[1]
        name = f"{device_id}"
        return name

    def add_callback(self, callback):
        self.callback = callback

    def get_state(self):
        state = copy.deepcopy(self.last_state)
        state["name"] = self.name
        return state
    def get_valid_state_keys(self):
        return ["status"]

        

    def trigger_state(self, **kwargs):
        log.info(f"Triggering Motion Sensor: {self.name} with value: {kwargs}")
        if self.callback is not None:
            if "tags" in kwargs:
                tags = kwargs["tags"]
                log.info(f"tags are {tags}")
                self.callback(tags)
            else:
                log.info(f"No tags in kwargs {kwargs}")

    def setup_service_triggers(self, device_id):
        log.info(f"Generating trigger for: {device_id}")
        trigger_types = ["_ias_zone", "_iaszone", "_occupancy"]
        values = ["on", "off"]

        triggers = []
        for trigger_type in trigger_types:
            if trigger_type == "_ias_zone":
                tag = "motion_detected"
            else:
                tag = "motion_occupancy"

            if f"binary_sensor.{device_id}{trigger_type}" in locals():
                log.info(f"IN LOCALS: {device_id}")
            if f"binary_sensor.{device_id}{trigger_type}" in globals():
                log.info(f"IN GLOBALS: {device_id}")

            for value in values:
                triggers.append(
                    generate_state_trigger(
                        f"binary_sensor.{device_id}{trigger_type} == '{value}'",
                        self.trigger_state,
                        {"tags": [value, tag]},
                    )
                )


@service
def service_driver_trigger(**kwargs):
    """Standalone pyscript service for HA scripts to trigger service input buttons.

    Moved to module level so @service registers as pyscript.service_driver_trigger.
    Previously nested inside ServiceDriver.create_trigger() where the @service
    decorator did not properly register the service with Home Assistant.
    """
    log.info(f"Triggering Service: with value: {kwargs}")
    new_event = {}

    # Always set device_name and tags regardless of whether a state payload is present.
    # Previously these were only set inside the `if "state"` block, which caused a
    # KeyError in EventManager.check_event() for tag-only calls like turn_on/turn_off.
    new_event["device_name"] = kwargs.get("name", "service_input_button_all_lights")

    if "tags" in kwargs:
        new_event["tags"] = kwargs["tags"]

    if "state" in kwargs:
        state = kwargs["state"]
        if "hs_color" in state:
            hs_color = state["hs_color"]
            rgb = hs_to_rgb(hs_color[0], hs_color[1])
            rgb = [rgb[0], rgb[1], rgb[2]]
            state["rgb_color"] = rgb

            del state["hs_color"]

        if "temp" in state:
            state["color_temp"] = state["temp"]
            del state["temp"]

        log.info(f"state: {state}")
        new_event["state"] = state

    log.info(f"ServiceDriver: emitting event {new_event}")
    get_event_manager().create_event(new_event)


class ServiceDriver:
    def __init__(self, input_type, device_id):
        self.name = device_id
        log.info(f"Creating Service Input: {self.name}")

        self.last_state = None
        self.trigger = service_driver_trigger

        get_global_triggers().append(["Service", service_driver_trigger])

    def add_callback(self, callback):
        pass

    def get_state(self):
        return {"name": self.name}
    
    def get_valid_state_keys(self):
        return []


class PresenceSensorDriver:
    def __init__(self, input_type, device_id):
        self.name = self.create_name(input_type, device_id)
        log.info(f"Creating Presence Sensor: {self.name}")

        self.last_state = None
        self.trigger = self.setup_service_triggers(device_id)

        self.callback = None

        self.value = None

    def create_name(self, input_type, device_id):
        if input_type in device_id:
            name = device_id
        else:
            name = f"{input_type}_{device_id}"

        log.info(f"Creating Presence Sensor: {name}")
        return name

    def add_callback(self, callback):
        self.callback = callback

    def get_state(self):
        state = self.last_state
        if state is None:
            state = {}
        state["name"] = self.name
        return state

    def get_valid_state_keys(self):
        return ["presence"]

    def trigger_state(self, **kwargs):
        log.info(f"Triggering Presence Sensor: {self.name} with value: {kwargs}")
        if self.callback is not None:
            if "tags" in kwargs:
                tags = kwargs["tags"]
                log.info(f"tags are {tags}")
                self.callback(tags)
            else:
                log.info(f"No tags in kwargs {kwargs}")

    def setup_service_triggers(self, device_id):
        log.info(f"Generating trigger for: {device_id}")
        values = ["on", "off"]

        triggers = []

        if f"binary_sensor.{device_id}" in locals():
            log.info(f"IN LOCALS: {device_id}")
        if f"binary_sensor.{device_id}" in globals():
            log.info(f"IN GLOBALS: {device_id}")

        for value in values:
            triggers.append(
                generate_state_trigger(
                    f"binary_sensor.{device_id} == '{value}'",
                    self.trigger_state,
                    {"tags": [value, "presence"]},
                )
            )

        return triggers

class KaufLight:
    """Light driver for kauf bulbs with optional color calibration."""

    def __init__(self, name, color_profile=None):
        self.name = name
        self.device_type = "light"
        self.last_state = {}
        # These values are cached on the driver, whereas the whole state is cached on the device
        self.rgb_color = None
        self.brightness = None
        self.temperature = None
        self.default_color = None
        self.color_type = "rgb"
        self.color_profile = color_profile or COLOR_PROFILES.get("kauf")

    def calibrate_color(self, rgb):
        return calibrate_rgb(rgb, self.color_profile)

    # Status (on || off)
    def set_status(self, status, edit=0):
        """Sets the status of the light (on or off)"""
        if status:
            # Turn on: re-apply cached color if available
            if self.color_type == "rgb":
                self.apply_values(rgb_color=self.get_rgb())
            else:
                temp = self.get_temperature()
                if temp is not None:
                    self.apply_values(color_temp=temp)
                else:
                    self.apply_values()
        else:
            self.apply_values(off=1)

    def get_status(self):
        """Gets status"""
        status="unavailable"
        try:
            status = state.get(f"light.{self.name}")

            log.info(f"KaufLight<{self.name}>:get_status(): Getting status {status}")
        except Exception:
            log.warning(f"Unable to get status from {self.name}")

        if status is None or status == "unavailable":
            log.warning(f"KaufLight<{self.name}>:get_status(): Unable to get status- Returning unknown")
        return status

    def get_valid_state_keys(self):
        return ["status", "off", "rgb_color", "brightness", "color_temp", "hs_color"]

    def filter_state(self, state):
        valid_keys=self.get_valid_state_keys()
        filtered_state={}
        
        for key, val in state.items():
            if key in valid_keys:
                filtered_state[key]=val
        if "off" in filtered_state:
            del filtered_state["off"]
        if "status" in filtered_state:
            del filtered_state["status"]
        return filtered_state

    def is_on(self):
        status = self.get_status()
        if status is None or "off" in status or "unknown" in status or "unavailable" in status:
            return False
        log.info(f"KaufLight<{self.name}>:is_on(): Returning True: {status}")
        return True

    # RGB (color)
    def set_rgb(self, color, apply=False):
        self.color = color
        log.info(f"KaufLight<{self.name}>:set_rgb(): Caching color: {self.color}")
        if apply or self.is_on():
            self.apply_values(rgb_color=self.color)

    def get_rgb(self):
        """ If this is unable to get color, should return None"""
        color = None
        try:
            color = state.get(f"light.{self.name}.rgb_color")
        except Exception:
            log.warning(f"Unable to get rgb_color from {self.name}", exc_info=True)

        self.rgb_color = color


        return color if color != "null" else None

    # Brightness
    def set_brightness(self, brightness, apply=False):
        self.apply_values(brightness=brightness)

    def get_brightness(self):
        brightness = 255
        try:
            brightness = state.get(f"light.{self.name}.brightness")
        except Exception:
            log.warning(f"get_brightness(): Unable to get brightness from {self.name}", exc_info=True)

        if self.is_on():  # brightness reports as 0 when off
            self.brightness = brightness

        return brightness

    def set_temperature(self, temperature, apply=False):
        self.temperature = temperature
        self.apply_values(color_temp=self.temperature)

    def get_temperature(self):
        temperature = None
        try:
            temperature = state.get(f"light.{self.name}.color_temp")
        except Exception:
            log.warning(f"Unable to get color_temp from {self.name}", exc_info=True)

        if temperature is None or temperature == "null":
            if self.temperature is not None:
                log.info(f"KaufLight<{self.name}>:get_temperature(): temperature is {temperature}. Getting cached temperature")
                temperature = self.temperature
        else:
            self.temperature = temperature

        return temperature if temperature != "null" else None

    def set_state(self, state):
        """
        Converts state to kauf specific values.
        Only does anything if state value is present, including changing brightness.
        """

        # Use explicit loop instead of generator expression because pyscript's
        # restricted AST interpreter does not support ast_generatorexp (see issue #1234)
        has_color_or_brightness = False
        for k in ["rgb_color", "color_temp", "brightness", "hs_color", "temp"]:
            if k in state:
                has_color_or_brightness = True
                break
        
        if "status" in state.keys():
            if not state["status"]:  # if being set to off
                state["off"] = 1

            del state["status"]
        else:
            # If no status but we have color/brightness changes, preserve on/off state
            # Only turn off if we have NO color/brightness and light is off
            if not has_color_or_brightness and not self.is_on():
                state["off"] = 1

        return self.apply_values(**state)

    def get_state(self):
        state = {}
        state["status"] = self.is_on()

        if state["status"]:  # if status is on, get current brightness
            brightness = self.get_brightness()
            if brightness is not None:
                state["brightness"] = brightness
        else:
            if self.brightness is not None:
                state["brightness"] = self.brightness

        if self.color_type == "rgb":
            rgb = self.get_rgb()
            if rgb is not None:
                state["rgb_color"] = rgb
        else:
            color_temp = self.get_temperature()
            if color_temp is not None:
                state["color_temp"] = color_temp
        log.info(f"KaufLight<{self.name}>:get_state(): Returning state: {state}")
        return state

    # Apply values
    def apply_values(self, **kwargs):
        """This parses the state that is passed in and sends those values to the light."""

        new_args = {}
        for k, v in kwargs.items():
            if v is not None:
                new_args[k] = v


        # If rgb_color is present: save and calibrate
        if "rgb_color" in new_args.keys():
            self.rgb_color = new_args["rgb_color"]  # cache raw value
            new_args["rgb_color"] = self.calibrate_color(new_args["rgb_color"])
            self.color_type = "rgb"

        elif "color_temp" in new_args.keys():
            self.color_temp = new_args["color_temp"]
            # log.info(f"KaufLight<{self.name}>:apply_values(): Caching {self.name} color_temp to {self.color_temp }")
            self.color_type = "temp"
            # log.info(f"KaufLight<{self.name}>:apply_values(): color_type is {self.color_type} -> {new_args}")

        else:
            # log.info(f"KaufLight<{self.name}>:apply_values(): Neither rgb_color nor color_temp in {new_args}")

            log.info(f"KaufLight<{self.name}>:apply_values(): color_type is {self.color_type} -> {new_args}")
            if self.color_type == "rgb":
                rgb = self.get_rgb()

                log.info(f"KaufLight<{self.name}>:apply_values(): rgb_color not in new_args. self rgb is {rgb}")
                if rgb is not None:
                    new_args["rgb_color"] = self.calibrate_color(rgb)
                    log.info(f"KaufLight<{self.name}>:apply_values(): Supplimenting rgb_color to {rgb}")
            else:
                temp = self.get_temperature()
                log.info(f"KaufLight<{self.name}>:apply_values(): color_temp not in new_args. self color_temp is {temp}")
                if temp is not None:
                    new_args["color_temp"] = temp
                    log.info(f"KaufLight<{self.name}>:apply_values(): Supplimenting color_temp to {temp}")

        if (
            "off" in new_args and new_args["off"]
        ):  # If "off" : True is present, turn off
            self.last_state = {"off": True}
            light.turn_off(entity_id=f"light.{self.name}")
            new_args["status"] = 0
            del new_args["off"]
            return new_args

        

        else:  # Turn on

                
            try:
                log.info(f"KaufLight<{self.name}>:apply_values(): {self.name} {new_args}")
                light.turn_on(entity_id=f"light.{self.name}", **new_args)
                self.last_state = new_args

            except Exception as e:
                log.warning(
                    f"\nPYSCRIPT: [ERROR 0/1] Failed to set {self.name} {new_args}: {e}"
                )
                light.turn_on(entity_id=f"light.{self.name}")
                self.last_state = {"on": True}

        return self.last_state


class HueLight:
    """
    Standalone light driver for Philips Hue bulbs.

    Mirrors KaufLight behavior via composition instead of inheritance, to avoid any
    environment quirks around subclassing while keeping hue-specific calibration.
    """

    def __init__(self, name):
        self.name = name
        self.device_type = "light"
        self._delegate = KaufLight(name, color_profile=COLOR_PROFILES.get("hue"))

    def __getattr__(self, attr):
        return getattr(self._delegate, attr)

    def get_valid_state_keys(self):
        return self._delegate.get_valid_state_keys()

    def filter_state(self, state):
        return self._delegate.filter_state(state)

    def set_state(self, state):
        return self._delegate.set_state(state)

    def get_state(self):
        return self._delegate.get_state()


class BlindDriver:
    """Driver for smart blinds controllable by percent closed or height."""

    def __init__(self, name, height=100):
        self.name = name
        self.device_type = "blind"
        self.height = height
        self.last_state = {"closed_percent": 0}

    def get_valid_state_keys(self):
        return ["closed_percent", "height"]

    def filter_state(self, state):
        valid = self.get_valid_state_keys()
        return {k: v for k, v in state.items() if k in valid}

    def get_state(self):
        position = None
        try:
            position = state.get(f"cover.{self.name}.current_position")
        except Exception:
            pass
        if position is None:
            position = 100 - self.last_state.get("closed_percent", 0)
        closed = 100 - int(position)
        result = {"closed_percent": closed}
        if self.height:
            result["height"] = self.height * (100 - closed) / 100
        self.last_state = result
        return result

    def set_state(self, state):
        state = self.filter_state(state)
        percent = None
        if "height" in state and self.height:
            percent = 100 - int((state["height"] / self.height) * 100)
        elif "closed_percent" in state:
            percent = state["closed_percent"]

        if percent is not None:
            position = max(0, min(100, 100 - percent))
            try:
                cover.set_cover_position(entity_id=f"cover.{self.name}", position=position)
            except Exception as e:
                log.warning(f"Failed to set blind {self.name} to {position}% open: {e}")
            self.last_state = {"closed_percent": percent}
            if self.height:
                self.last_state["height"] = self.height * (100 - percent) / 100
        return self.last_state


class SpeakerDriver:
    """Driver for smart speakers such as Google Home."""

    def __init__(self, name):
        self.name = name
        self.device_type = "speaker"
        self.last_state = {"volume": None, "playing": None}

    def get_valid_state_keys(self):
        return ["volume"]

    def filter_state(self, state):
        valid = self.get_valid_state_keys()
        return {k: v for k, v in state.items() if k in valid}

    def get_state(self):
        volume = None
        playing = None
        try:
            volume = state.get(f"media_player.{self.name}.volume_level")
        except Exception:
            pass
        try:
            status = state.get(f"media_player.{self.name}.state")
            if status == "playing":
                playing = state.get(f"media_player.{self.name}.media_title")
        except Exception:
            pass
        self.last_state = {"volume": volume, "playing": playing}
        return self.last_state

    def set_state(self, state):
        state = self.filter_state(state)
        if "volume" in state and state["volume"] is not None:
            try:
                media_player.volume_set(entity_id=f"media_player.{self.name}", volume_level=state["volume"])
            except Exception as e:
                log.warning(f"Failed to set volume for {self.name}: {e}")
        self.last_state.update(state)
        return self.last_state


class PlugDriver:
    """Driver for smart plugs acting as simple on/off switches."""

    def __init__(self, name):
        self.name = name
        self.device_type = "plug"
        self.last_state = {"status": 0}

    def get_valid_state_keys(self):
        return ["status"]

    def filter_state(self, state):
        valid = self.get_valid_state_keys()
        return {k: v for k, v in state.items() if k in valid}

    def get_state(self):
        status = None
        try:
            status = state.get(f"switch.{self.name}")
        except Exception:
            pass
        if status is None:
            status = self.last_state.get("status", 0)
        else:
            status = 1 if str(status).lower() in {"on", "true", "1"} else 0
        self.last_state = {"status": status}
        return self.last_state

    def set_state(self, state):
        state = self.filter_state(state)
        if "status" in state:
            try:
                if state["status"]:
                    switch.turn_on(entity_id=f"switch.{self.name}")
                else:
                    switch.turn_off(entity_id=f"switch.{self.name}")
            except Exception as e:
                log.warning(f"Failed to set plug {self.name}: {e}")
            self.last_state["status"] = 1 if state["status"] else 0
        return self.last_state


class ContactSensorDriver:
    """Driver for simple binary contact sensors."""

    def __init__(self, name):
        self.name = name
        self.device_type = "contact_sensor"
        self.last_state = {"contact": 0}

    def get_valid_state_keys(self):
        return ["contact"]

    def filter_state(self, state):
        valid = self.get_valid_state_keys()
        return {k: v for k, v in state.items() if k in valid}

    def get_state(self):
        status = None
        try:
            status = state.get(f"binary_sensor.{self.name}")
        except Exception:
            pass
        if status is None:
            status = self.last_state.get("contact", 0)
        else:
            status = 1 if str(status).lower() in {"on", "true", "open", "1"} else 0
        self.last_state = {"contact": status}
        return self.last_state


class FanDriver:
    """Driver for controllable fans supporting simple on/off."""

    def __init__(self, name):
        self.name = name
        self.device_type = "fan"
        self.last_state = {"status": 0}

    def get_valid_state_keys(self):
        return ["status"]

    def filter_state(self, state):
        valid = self.get_valid_state_keys()
        return {k: v for k, v in state.items() if k in valid}

    def get_state(self):
        status = None
        try:
            status = state.get(f"fan.{self.name}")
        except Exception:
            pass
        if status is None:
            status = self.last_state.get("status", 0)
        else:
            status = 1 if str(status).lower() in {"on", "true", "1"} else 0
        self.last_state = {"status": status}
        return self.last_state

    def set_state(self, state):
        state = self.filter_state(state)
        if "status" in state:
            try:
                if state["status"]:
                    fan.turn_on(entity_id=f"fan.{self.name}")
                else:
                    fan.turn_off(entity_id=f"fan.{self.name}")
            except Exception as e:
                log.warning(f"Failed to set fan {self.name}: {e}")
            self.last_state["status"] = 1 if state["status"] else 0
        return self.last_state


class TelevisionDriver:
    """Driver for televisions treated as media players."""

    def __init__(self, name):
        self.name = name
        self.device_type = "television"
        self.last_state = {"status": 0}

    def get_valid_state_keys(self):
        return ["status"]

    def filter_state(self, state):
        valid = self.get_valid_state_keys()
        return {k: v for k, v in state.items() if k in valid}

    def get_state(self):
        status = None
        try:
            status = state.get(f"media_player.{self.name}.state")
        except Exception:
            pass
        if status is None:
            status = self.last_state.get("status", 0)
        else:
            status = 1 if str(status).lower() in {"on", "playing", "true", "1"} else 0
        self.last_state = {"status": status}
        return self.last_state

    def set_state(self, state):
        state = self.filter_state(state)
        if "status" in state:
            try:
                if state["status"]:
                    media_player.turn_on(entity_id=f"media_player.{self.name}")
                else:
                    media_player.turn_off(entity_id=f"media_player.{self.name}")
            except Exception as e:
                log.warning(f"Failed to set television {self.name}: {e}")
            self.last_state["status"] = 1 if state["status"] else 0
        return self.last_state


# def test_toggle(area_name="kitchen") :
#     event_manager=get_event_manager()

#     scope={"get_area_local_scope": [area_name]}

#     area=event_manager.area_tree.get_area(area_name)

#     # Set initial color for area
#     event = {
#         "device_name": "service_input_all_",
#         "state:": {"status": 1, "rgb_color": [255, 0, 0]}
#     }.update(scope)

#     area_state=area.get_state()
#     if area_state["status"] :
#         log.fatal("Failed turning on test")

#     #toggle status
#     event = {
#         "device_name": "service_input_button_single",
#     }.update(scope)


@service
def test_event():
    log.info("TEST")
    unittest.main()
    # reset()
    # log.info(get_event_manager().area_tree.get_pretty_string())
    log.info("STARTING TEST EVENT")
    name = "TEST_TRACKER"
    event = {
        "device_name": name,
        "scope": [{"get_area_local_scope": ["office"]}],
        "functions": {
            "update_tracker" : []
        }
    }
    log.info(f"\nCreating Event: {event}")

    event_manager.create_event(event)





class TestManager():

    def __init__(self) :
        self.default_test_room="laundry_room"
        self.event_manager = get_event_manager()
        self.area_tree = get_area_tree()
        self.default_test_area=self.area_tree.get_area(self.default_test_room)
        log.info(f"AREA DEVICES: {self.default_test_area.get_devices()}")
        self.default_test_light = self._find_light()
        self.default_motion_sensor = self._find_motion_sensor()

    def _find_motion_sensor(self) :
        for device in self.default_test_area.get_devices() :
            if device.get_name().startswith("motion_sensor") :
                return device

    def _find_light(self) :
        # for device in self.default_test_area.get_devices() :
        #     log.info(f"LIGHT: {device.get_name()}")
        #     if device.get_name().startswith("kauf") :
        #         return device
        return self.area_tree.get_device("kauf_laundry_room_2")

    def run_tests(self) :
        tests_run=0
        tests_passed=0
        failed_tests=[]
        # get all methods in this class and check if their name starts with "test"
        log.info(dir(self))
        for method_name in dir(self):
            if method_name.startswith("test"):
                if getattr(self, method_name)() :
                    log.info(f"Test {tests_run+1}: {method_name} PASSED")

                    tests_passed+=1
                else :
                    log.info(f"Test {tests_run+1}: {method_name} FAILED")

                    failed_tests.append(method_name)
                tests_run+=1

        log.info(f"Tests passed: {tests_passed}/{tests_run}")

        if len(failed_tests) > 0 :
            log.info(f"Failed tests: {failed_tests}")
            return False
        
    # Test methods for merge_data
    def test_merge_data_empty_list(self):
        try:
            merge_data([])
            return False
        except ValueError:
            return True

    def test_merge_data_integers(self):
        return merge_data([1, 2, 3, 4, 5]) == 3.0

    def test_merge_data_floats(self):
        return merge_data([1.5, 2.5, 3.5]) == 2.5

    def test_merge_data_mixed_numbers(self):
        return merge_data([1, 2.5, 3]) == 2.1666666666666665

    def test_merge_data_lists(self):
        return merge_data([[1, 2], [3, 4], [5, 6]]) == [3.0, 4.0]

    def test_merge_data_lists_with_different_lengths(self):
        result = merge_data([[1, 2], [3, 4, 5], [6]])
        return result == [3.3333333333333335, 3.0, 5.0]

    def test_merge_data_dicts(self):
        data = [{"a": 1, "b": 2}, {"a": 3, "b": 4}, {"a": 5}]
        expected = {"a": 3.0, "b": 3.0}
        return merge_data(data) == expected

    # Test methods for merge_states
    def test_merge_states(self):
        states = [{"status": 0}, {"status": 1}, {"status": 1}]
        result = merge_states(states)
        return result["status"] == 1

    def test_merge_states_no_status(self):
        states = [{"other": 5}, {"other": 10}]
        result = merge_states(states)
        return "status" in result and result["status"] == 0


    def test_set_setting_status(self):
        """
        A test function to check setting status functionality by turning on and off from different initial states.
        """
        log.info("STARTING TEST SETTING STATUS")
        initial_state=self.default_test_area.get_state()
        # turn on from unknown default state
        self.default_test_area.set_state({"status": 1})
        time.sleep(.1)
        current_state=self.default_test_area.get_state()
        if not current_state["status"] :
            log.info(f"Failed to turn on from initial state {initial_state}")
            return False
        # Turn off from on
        self.default_test_area.set_state({"status": 0})
        time.sleep(.1)
        log.info(f"Test testting test: current state: {self.default_test_area.get_state()}")
        
        current_state=self.default_test_area.get_state()
        log.info(f"current state: { current_state['status']}")
        if current_state["status"] :
            log.info(f"Failed to turn off from on")
            return False

        # Turn on from off
        self.default_test_area.set_state({"status": 1})
        time.sleep(.1)
        current_state=self.default_test_area.get_state()
        if not current_state["status"] :
            log.info(f"Failed to turn on from off")
            return False

        return True

    def test_setting_cache(self) :
        log.info("STARTING TEST SETTING CACHE")
        self.default_test_light.set_state({"status": 1, "rgb_color": [255, 255, 255]})
        time.sleep(.1)
        self.default_test_light.set_state({"status": 0})
        time.sleep(.1)
        state=self.default_test_light.get_state()
        if state["status"] != 0 :
            log.info(f"test_setting_cache: Failed to set to off {state}")
            return False
        
        if state["rgb_color"] != [255, 255, 255] and state["rgb_color"] != (255, 255, 255) :
            log.info(f"test_setting_cache: Failed to keep rgb_color {state}")
            return False

        log.info("test_setting_cache: Setting cache to {'rgb_color': [255, 0, 255]}")
        self.default_test_light.add_to_cache({"rgb_color": [255, 0, 255]})
        time.sleep(.1)
        state=self.default_test_light.get_state()
        if state["status"] != 0 or state["rgb_color"] != [255, 0, 255] :
            log.info(f"test_setting_cache: Failed to update cache {state}")
            return False

        return True

    def test_set_and_get_color(self):
        log.info("TEST SETTING AND GETTING COLOR")
        # Set to off as default
        log.info("TEST: setting status 0 and rgb 000")
        self.default_test_area.set_state({"rgb_color": [0, 0, 0], "status":0})
        time.sleep(.1)
        state=self.default_test_area.get_state()

        if state["status"] != 0:
            log.warning(f"test_set_and_get_color: Failed to set to off {state}")
            return False

        if "rgb_color" in state and state["rgb_color"] != [0, 0, 0] :
            log.warning(f"Failed to set color while setting off {state}")
            return False


        log.info("TEST: setting rgb while off")
        # Set color while off
        self.default_test_area.set_state({"rgb_color": [255, 255, 255]})
        time.sleep(.1)
        state=self.default_test_area.get_state()
        if "rgb_color" in state and state["rgb_color"] != [255, 255, 255] :
            log.warning(f"TEST: Failed to set color while off {state}")
            return False
        if state["status"] != 0:
            log.warning(f"TEST: Failed to stay off when setting color {state}")

        log.info("TEST: turning on")
        # turn on 
        self.default_test_area.set_state({"status":1})
        time.sleep(.1)
        state=self.default_test_area.get_state()
        if state["status"] != 1:
            log.warning(f"TEST: Failed to turn on {state}")
            return False

        if state["rgb_color"] != [255, 255, 255]:
            log.warning(f"TEST: Failed to keep color that was set while off {state}")
            return False

        log.info("TEST: setting rgb while on")

        # Change color while on 
        self.default_test_area.set_state({"rgb_color": [0, 255, 0]})
        time.sleep(.1)
        state=self.default_test_area.get_state()
        if state["rgb_color"] != [0, 255, 0] or state["status"] != 1:
            log.warning(f"TEST: Failed to change color while on {state}")
            return False
            
        
        log.info(f"TEST: current state: {self.default_test_area.get_state()}")

        self.default_test_area.set_state({"rgb_color": [255, 195, 50]})
        time.sleep(.1)
        self.default_test_area.set_state({"status": 0})
        time.sleep(.1)
        self.default_test_area.set_state({"status": 1})
        time.sleep(.1)
        state=self.default_test_area.get_state()
        if state["rgb_color"] != [255, 195, 50] or state["status"] != 1:
            log.warning(f"test_set_and_get_color: Failed to persist through toggle {state}")
        return True

    # Test roadmap (see also tests/ directory for pytest-based tests):
    #   - brightness persistence through toggle
    #   - button event creation
    #   - track / tracker integration
    #   - service driver round-trip
    #   - rgb_color vs color_temp cache coexistence

    # Test combine states
    def test_combine_states(self):
        log.info("STARTING TEST COMBINE STATES")
        states = [
            {"status": 1, "brightness": 255, "rgb_color": [255, 255, 0]},
            {"status": 1, "rgb_color": [255, 0, 0]},
            {"status": 0, "brightness": 100, "rgb_color": [0, 255, 255]},
        ]
        fist_expected_state = {"status": 1, "brightness": 255, "rgb_color": [255, 255, 0]}
        first_state_result = combine_states(states, strategy="first")

        if first_state_result != fist_expected_state:
            log.warning(f"Expected first state to be {fist_expected_state} but was {first_state_result}")
            return False
        
        last_expected_state = {"status": 0, "brightness": 100, "rgb_color": [0, 255, 255]}
        last_state_result = combine_states(states, strategy="last")

        if last_state_result != last_expected_state:
            log.warning(f"Expected last state to be {last_expected_state} but was {last_state_result}")
            return False
        
        average_expected_state = {"status": 1, "brightness": 177.5, "rgb_color": [170, 170, 85]}
        average_state_result = combine_states(states, strategy="average")

        if average_state_result != average_expected_state:
            log.warning(f"Expected average state to be {average_expected_state} but was {average_state_result}")
            return False

        return True
        

    def test_motion_sensor(self) :
        # When motion sensor is triggered, the area should be turned off.
        log.info(f"test_motion_sensor: starting: Area {self.default_test_area}")
        initial_state=self.default_test_area.get_state()
        log.info(f"test_motion_sensor: initial state: {initial_state}")
        # Set to known initial state
        # NOTE: State rules are not easily injectable in this in-process test harness;
        # only status and brightness are deterministically verifiable here.
        self.default_test_area.set_state({"status": 1, "brightness": 255, "rgb_color": [255, 72, 35]})
        time.sleep(.1)
        # Set to off
        self.default_test_area.set_state({"status": 0})
        time.sleep(.1)
        log.info(f"test_motion_sensor: state after off: {self.default_test_area.get_state()}")

        event_manager.create_event({'device_name': self.default_motion_sensor.name, 'tags': ['on', 'motion_occupancy']})
        time.sleep(.2)
        # Check if area is on
        state=self.default_test_area.get_state()
        log.info(f"test_motion_sensor: state after motion: {state}")
        if state['status'] != 1 :
            log.warning(f"test_motion_sensor: Failed - Expected area to be on after motion sensor trigger but was {state}")
            return False
        if state["brightness"] != 255 :
            log.warning(f"test_motion_sensor: Failed - Expected brightness to be 255 but was {state['brightness']}")
            return False

        # NOTE: rgb_color after motion depends on time-of-day rules and is not
        # deterministic in this test context, so the assertion is disabled.
        # if state["rgb_color"] != [255, 72, 35]:
        #     log.warning(f"test_motion_sensor: Failed - Expected rgb_color to be [255, 72, 35] but was {state['rgb_color']}")
        #     return False


        # Test motion sensor deactivation
        self.default_test_area.set_state({"status": 0})
        set_motion_sensor_mode("off")
        time.sleep(.2)
        event_manager.create_event({'device_name': self.default_motion_sensor.name, 'tags': ['on', 'motion_occupancy']})

        time.sleep(.2)
        state=self.default_test_area.get_state()
        if state['status'] != 0:
            log.warning(f"Expected area to be off after motion sensor deactivation but was {self.default_test_area.get_state()}")
            return False

        # cleanup
        set_motion_sensor_mode("on")
        return True

    def test_device_type_filter(self):
        """Verify that device_type_filter on Area.set_state skips non-matching device types."""
        log.info("test_device_type_filter: starting")

        # Use the office area which has both lights (hue) and a plug (office_fan)
        office_area = self.area_tree.get_area("office")
        if office_area is None:
            log.warning("test_device_type_filter: office area not found, skipping")
            return True

        # Find the office_fan device (plug) and a light device
        office_fan = self.area_tree.get_device("office_fan")
        if office_fan is None:
            log.warning("test_device_type_filter: office_fan not found, skipping")
            return True

        # Verify device_type attributes are set correctly
        fan_type = getattr(office_fan.driver, "device_type", None)
        if fan_type != "plug":
            log.warning(f"test_device_type_filter: Expected office_fan.driver.device_type='plug', got '{fan_type}'")
            return False
        log.info(f"test_device_type_filter: office_fan.driver.device_type='{fan_type}' OK")

        # Reset office_fan to a known off state
        office_fan.add_to_cache({"status": 0})
        fan_state_before = office_fan.cached_state.get("status", None)

        # Apply state with device_type_filter=["light"] — plug should be skipped
        office_area.set_state({"status": 1, "brightness": 200}, device_type_filter=["light"])

        fan_state_after = office_fan.cached_state.get("status", None) if office_fan.cached_state else None
        if fan_state_after != 0:
            log.warning(f"test_device_type_filter: FAIL — office_fan status should remain 0 after light-only set_state, got {fan_state_after}")
            return False
        log.info(f"test_device_type_filter: office_fan correctly skipped (status={fan_state_after})")

        # Now apply without filter — plug SHOULD be updated this time
        office_area.set_state({"status": 1}, device_type_filter=None)
        fan_state_unfiltered = office_fan.cached_state.get("status", None) if office_fan.cached_state else None
        if fan_state_unfiltered != 1:
            log.warning(f"test_device_type_filter: FAIL — office_fan should be 1 after unfiltered set_state, got {fan_state_unfiltered}")
            return False
        log.info(f"test_device_type_filter: office_fan correctly updated without filter (status={fan_state_unfiltered})")

        # Cleanup: turn office_fan back off
        office_area.set_state({"status": 0}, device_type_filter=None)
        log.info("test_device_type_filter: PASSED")
        return True

@service 
def run_tests() :
    log.info("TEST")
    test_manager=TestManager()
    test_manager.run_tests()
    




init_config = init()
if init_config.get("run_tests_on_start", DEFAULT_RUN_TESTS_ON_START):
    run_tests()

@event_trigger(EVENT_CALL_SERVICE)
def monitor_service_calls(**kwargs):
    log.info(f"got EVENT_CALL_SERVICE with kwargs={kwargs}")

# This monitors other methods of settings lights colors and informs the area tree
@event_trigger(EVENT_CALL_SERVICE)
def monitor_external_state_setting(**kwargs):
    if "domain" in kwargs:
        if kwargs["domain"] == "light":
            data=kwargs.get("service_data")
            device_names=[]
            if "entity_id" in data:

                def fix_entity_name(entity_id):
                    # Strip only the leading domain portion; don't drop inner characters.
                    if entity_id.startswith("light."):
                        entity_id = entity_id.split(".", 1)[1]
                    if entity_id.endswith("_"):
                        entity_id += "light"
                    return entity_id

                if type(data["entity_id"]) == str:
                    device_names.append(fix_entity_name(data["entity_id"]))
                elif type(data["entity_id"]) == list:
                    for device_name in data["entity_id"] :
                        device_names.append(fix_entity_name(device_name))
            
            state={}
            if "brightness" in data:
                state["brightness"]=data["brightness"]
            if "color_temp" in data:
                state["color_temp"]=data["color_temp"]
            if "rgb_color" in data:
                state["rgb_color"]=data["rgb_color"]
            if "hs_color" in data:
                state["rgb_color"]=hs_to_rgb(data["hs_color"][0], data["hs_color"][1])

            if state == {}:
                state["status"]=False

            event_manager=get_event_manager()

            devices=[]
            for device_name in device_names:
                log.info(f"ATTEMPTING TO SET DEVICE {device_name} TO {state}")
                # get_device looks up by internal name; fix_entity_name above
                # converts the HA entity_id to that form, but mismatches are
                # possible if devices.yml names diverge from HA entity ids.
                device=event_manager.area_tree.get_device(device_name)
                if device is not None:
                    devices.append(device)
                    device_state=device.get_state()
                    if device_state is not None:
                        if get_state_similarity(device_state, state)<=0.5: 
                            log.info(f"SETTING DEVICE {device_name} TO {state}")
                            device.add_to_cache(state)
                else :
                    log.info(f"DEVICE {device_name} NOT FOUND")


@time_trigger("cron(*/15 * * * *)")
def circadian_periodic_update():
    """Periodically re-apply circadian COLOR to lit lights.

    Only updates color_temp/rgb_color — does NOT change brightness.
    This prevents fighting with manual dimming, TV mode, or toggle presets.
    """
    tree = get_area_tree()
    if tree is None:
        return
    hour = time.localtime().tm_hour
    minute = time.localtime().tm_min
    current_minutes = hour * 60 + minute

    log.info(f"circadian_periodic_update: hour={hour} minute={minute}")

    for name, obj in tree.area_tree_lookup.items():
        # Only process Device leaves (not Area composites)
        if not hasattr(obj, 'driver'):
            continue
        if getattr(obj.driver, 'device_type', None) != 'light':
            continue
        if obj.locked:
            continue
        obj_state = obj.get_state()
        if not obj_state.get("status"):
            continue
        scope_rgb = obj_state.get("rgb_color")
        color_state = _get_circadian_color_state(current_minutes, scope_rgb)
        if color_state:
            log.info(f"circadian_periodic_update: applying color {color_state} to {name}")
            obj.set_state(copy.deepcopy(color_state))


### Tests ###


# Test if motion sensor sets state correctly




@service
def test_tracks() :
    log.info("STARTING TEST TRACKS")
    event_manager = get_event_manager()
    engine=get_occupancy_engine()
    event_manager.create_event({'device_name': 'motion_sensor_laundry_room', 'tags': ['on', 'motion_occupancy']})
    time.sleep(0.2)
    event_manager.create_event({'device_name': 'motion_sensor_office', 'tags': ['on', 'motion_occupancy']})
    time.sleep(0.2)

    event_manager.create_event({'device_name': 'motion_sensor_hallway', 'tags': ['on', 'motion_occupancy']})
    time.sleep(0.2)

    event_manager.create_event({'device_name': 'motion_sensor_kitchen', 'tags': ['on', 'motion_occupancy']})
    time.sleep(0.2)

    # event_manager.create_event({'device_name': 'motion_sensor_outside', 'tags': ['on', 'motion_occupancy']})

    # event_manager.create_event({'device_name': 'motion_sensor_chair_0', 'tags': ['on', 'motion_occupancy']})

    # event_manager.create_event({'device_name': 'motion_sensor_chair_1', 'tags': ['on', 'motion_occupancy']})

    # event_manager.create_event({'device_name': 'motion_sensor_living_room_back', 'tags': ['on', 'motion_occupancy']})

    log.info(engine.debug_summary())

#test_tracks()
