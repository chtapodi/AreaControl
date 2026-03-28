"""
Autodiscovery module for pyscript area_tree.

Queries Home Assistant's device and entity registries to automatically
discover devices and generate device entries.

Architecture:
- discovered.yml: Auto-generated device entries (append-only, stable ordering)
- devices.yml: Manual overrides (takes precedence)
- Merged on init for device_defs
"""

import os
import yaml
from collections import OrderedDict
from typing import Any, Dict, List, Optional, Set
try:
    from homeassistant.helpers import device_registry as ha_device_registry
    from homeassistant.helpers import entity_registry as ha_entity_registry
except Exception:
    ha_device_registry = None
    ha_entity_registry = None

try:
    from area_tree import log
except ImportError:
    import logging
    log = logging.getLogger("autodiscover")

DEFAULT_DISCOVERED_PATH = "./pyscript/discovered.yml"
DEFAULT_DISCOVERED_LAYOUT_PATH = "./pyscript/discovered_layout.yml"

DOMAIN_TO_TYPE = {
    "light": "light",
    "cover": "blind",
    "switch": "plug",
    "media_player": "speaker",
    "fan": "fan",
    "binary_sensor": "contact_sensor",
    "sensor": "sensor",
    "climate": "climate",
}

TYPE_FILTER_INFER = {
    "light": ["light"],
    "blind": ["blind"],
    "speaker": ["speaker"],
    "plug": ["plug"],
    "contact_sensor": ["contact"],
    "fan": ["fan"],
    "sensor": ["sensor"],
    "climate": ["climate"],
}

MANUFACTURER_PATTERNS = {
    "hue": ["hue", "philips", "signify"],
    "kauf": ["kauf", "fe"],
    "tuya": ["tuya", "_tz"],
    "shelly": ["shelly"],
    "sonoff": ["sonoff"],
    "ikea": ["ikea"],
}


def ordered_dump(data: Dict, stream=None, Dumper=yaml.SafeDumper, **kwargs):
    """Dump YAML with ordered dicts to preserve insertion order."""
    class OrderedDumper(Dumper):
        pass

    def _represent_dict(dumper, data):
        return dumper.represent_mapping("tag:yaml.org,2002:map", data.items())

    OrderedDumper.add_representer(OrderedDict, _represent_dict)
    return yaml.dump(data, stream, OrderedDumper, **kwargs)


def _infer_type_from_entity(entity, device_info: Optional[Dict] = None) -> tuple:
    """Infer device type from entity domain and device info."""
    domain = entity.domain
    
    primary_type = DOMAIN_TO_TYPE.get(domain, "unknown")
    
    filters = list(TYPE_FILTER_INFER.get(primary_type, []))
    
    manufacturer = (device_info.get("manufacturer", "") or "").lower() if device_info else ""
    model = (device_info.get("model", "") or "").lower() if device_info else ""
    name = (entity.original_name or entity.name or "").lower() if entity else ""
    
    for mfr_name, patterns in MANUFACTURER_PATTERNS.items():
        for pattern in patterns:
            if pattern in manufacturer or pattern in model or pattern in name:
                if primary_type == "light" and mfr_name in ["hue", "kauf"]:
                    filters = [mfr_name]
                    break
    
    if primary_type == "light" and "hue" not in filters and "kauf" not in filters:
        if "hue" in name or "lamp" in name:
            filters = ["light", "hue"]
        elif "kauf" in name or "ball" in name:
            filters = ["light", "kauf"]
    
    return primary_type, filters


def discover_devices(hass_obj=None) -> Dict[str, Dict]:
    """
    Query HA registries and discover all devices.
    
    Args:
        hass_obj: Optional hass object. If not provided, tries to get from area_tree.
    
    Returns:
        Dict mapping device_id (from entity_id) to device config.
    """
    hass = hass_obj
    
    if hass is None:
        try:
            from area_tree import hass as _hass
            hass = _hass
        except ImportError:
            pass
    
    if hass is None:
        try:
            import autodiscover
            hass = getattr(autodiscover, 'hass', None)
        except:
            pass
    
    if ha_device_registry is None or ha_entity_registry is None:
        log.warning("Autodiscovery: HA registries unavailable")
        return {}
    
    if hass is None:
        log.warning("Autodiscovery: hass object unavailable")
        return {}
    
    log.info(f"Autodiscovery: Using hass = {type(hass)}")
    
    try:
        device_registry = ha_device_registry.async_get(hass)
        entity_registry = ha_entity_registry.async_get(hass)
    except Exception as exc:
        log.warning(f"Autodiscovery: Failed to get registries: {exc}")
        return {}
    
    discovered = {}
    entity_to_device = {}
    
    for entity_id, entity in entity_registry.entities.items():
        if not entity.device_id:
            continue
        if entity.disabled_by:
            continue
        entity_to_device[entity_id] = entity.device_id
    
    device_entities = {}
    for device_id, device in device_registry.devices.items():
        device_entities[device_id] = {
            "name": device.name_by_user or device.name,
            "manufacturer": device.manufacturer,
            "model": device.model,
            "area_id": device.area_id,
        }
    
    primary_entities = {}
    for entity_id, entity in entity_registry.entities.items():
        if not entity.device_id:
            continue
        if entity.disabled_by:
            continue
            
        device_id = entity.device_id
        
        if device_id not in primary_entities:
            primary_entities[device_id] = {
                "entity": entity,
                "device_info": device_entities.get(device_id, {}),
                "domains": set(),
                "entities": [],
            }
        
        primary_entities[device_id]["domains"].add(entity.domain)
        primary_entities[device_id]["entities"].append(entity_id)
    
    for device_id, data in primary_entities.items():
        entity = data["entity"]
        device_info = data["device_info"]
        domains = data["domains"]
        
        entity_id = entity.entity_id
        if "." not in entity_id:
            continue
        
        domain, object_id = entity_id.split(".", 1)
        
        dtype, filters = _infer_from_domains(domains, object_id, device_info)
        
        entry = OrderedDict()
        entry["type"] = dtype
        if filters:
            entry["filters"] = filters
        
        if device_info.get("area_id"):
            entry["ha_area_id"] = device_info["area_id"]
        
        entry["ha_device_id"] = device_id
        entry["domains"] = sorted(domains)
        
        discovered[object_id] = entry
    
    log.info(f"Autodiscovery: Found {len(discovered)} devices from HA registry")
    return discovered


def _infer_from_domain(entity, data: Dict, device_info: Dict) -> tuple:
    """Infer type from domain and device characteristics."""
    domain = entity.domain
    
    if domain == "light":
        name = (entity.original_name or entity.name or "").lower()
        if "hue" in name or "lamp" in name:
            return "light", ["light", "hue"]
        elif "kauf" in name or "ball" in name or "fe" in name:
            return "light", ["light", "kauf"]
        return "light", ["light"]
    
    if domain == "cover":
        return "blind", ["blind"]
    
    if domain == "media_player":
        name = (entity.original_name or entity.name or "").lower()
        if "google" in name or "home" in name:
            return "speaker", ["speaker", "google_home"]
        return "speaker", ["speaker"]
    
    if domain == "switch":
        return "plug", ["plug"]
    
    if domain == "fan":
        return "fan", ["fan"]
    
    if domain == "binary_sensor":
        name = (entity.original_name or entity.name or "").lower()
        if "contact" in name or "door" in name or "window" in name:
            return "contact_sensor", ["contact"]
        return "sensor", ["sensor"]
    
    if domain == "sensor":
        return "sensor", ["sensor"]
    
    if domain == "climate":
        return "climate", ["climate"]
    
    return "unknown", []


def _infer_from_domains(domains: set, object_id: str, device_info: Dict) -> tuple:
    """Infer type from multiple domains, prioritizing primary device types."""
    name = object_id.lower()
    
    domain_priority = ["light", "cover", "media_player", "fan", "switch", "binary_sensor", "sensor", "climate"]
    
    for domain in domain_priority:
        if domain in domains:
            if domain == "light":
                if "hue" in name or "lamp" in name:
                    return "light", ["light", "hue"]
                elif "kauf" in name or "bulb" in name or "ball" in name or "fe" in name:
                    return "light", ["light", "kauf"]
                return "light", ["light"]
            
            if domain == "cover":
                return "blind", ["blind"]
            
            if domain == "media_player":
                if "google" in name or "home" in name or "speaker" in name:
                    return "speaker", ["speaker", "google_home"]
                if "tv" in name or "tv" in name:
                    return "speaker", ["speaker"]
                return "speaker", ["speaker"]
            
            if domain == "fan":
                return "fan", ["fan"]
            
            if domain == "switch":
                return "plug", ["plug"]
            
            if domain == "binary_sensor":
                if "contact" in name or "door" in name or "window" in name or "opening" in name:
                    return "contact_sensor", ["contact"]
                return "sensor", ["sensor"]
            
            if domain == "sensor":
                return "sensor", ["sensor"]
            
            if domain == "climate":
                return "climate", ["climate"]
    
    return "unknown", []


def load_existing_discovered(path: str = DEFAULT_DISCOVERED_PATH) -> Dict:
    """Load existing discovered.yml if it exists."""
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r") as f:
            return yaml.safe_load(f) or {}
    except Exception as e:
        log.warning(f"Autodiscovery: Failed to load {path}: {e}")
        return {}


def merge_with_existing(
    discovered: Dict,
    existing: Dict,
    manual: Dict
) -> tuple:
    """
    Merge discovered devices with existing config.
    
    Returns:
        (merged_devices, new_devices, updated_devices, conflicts)
    """
    merged = dict(manual)
    
    new_devices = {}
    updated_devices = {}
    conflicts = []
    
    for device_id, disc_info in discovered.items():
        if device_id in manual:
            continue
        
        if device_id in existing:
            existing_info = existing[device_id]
            if existing_info.get("type") != disc_info.get("type"):
                conflicts.append({
                    "device_id": device_id,
                    "existing": existing_info,
                    "discovered": disc_info,
                })
            merged[device_id] = existing_info
        else:
            new_devices[device_id] = disc_info
            merged[device_id] = disc_info
    
    return merged, new_devices, updated_devices, conflicts


def write_discovered(
    existing: Dict,
    new_devices: Dict,
    path: str = DEFAULT_DISCOVERED_PATH
) -> None:
    """Write discovered devices to file, preserving existing entries."""
    if not new_devices:
        return
    
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    
    merged = OrderedDict()
    
    for device_id, info in existing.items():
        merged[device_id] = info
    
    for device_id, info in sorted(new_devices.items()):
        if device_id not in merged:
            merged[device_id] = info
    
    try:
        with open(path, "w") as f:
            f.write("# Auto-generated - do not edit manually\n")
            f.write("# New devices are appended. Existing entries preserve order.\n\n")
            ordered_dump(merged, f)
        log.info(f"Autodiscovery: Wrote {len(new_devices)} new devices to {path}")
    except Exception as e:
        log.warning(f"Autodiscovery: Failed to write {path}: {e}")


def discover_layouts() -> Dict[str, List[str]]:
    """
    Discover area layouts from HA device registry.
    
    Returns:
        Dict mapping area_name to list of device_ids in that area.
    """
    try:
        from area_tree import hass
    except ImportError:
        hass = None
    
    if ha_device_registry is None or ha_entity_registry is None:
        return {}
    
    if hass is None:
        return {}
    
    try:
        device_registry = ha_device_registry.async_get(hass)
    except Exception as exc:
        log.warning(f"Autodiscovery: Failed to get device registry: {exc}")
        return {}
    
    area_devices = {}
    
    for device_id, device in device_registry.devices.items():
        if device.area_id:
            if device.area_id not in area_devices:
                area_devices[device.area_id] = []
            
            name = device.name_by_user or device.name or device_id
            area_devices[device.area_id].append(name)
    
    return area_devices


def generate_review_summary(
    new_devices: Dict,
    conflicts: List[Dict],
    existing_missing: List[str],
    output_path: str = "./pyscript/debug/autodiscovery_review.md"
) -> str:
    """Generate a summary of items needing manual review."""
    lines = [
        "# Autodiscovery Review Summary",
        "",
        f"Generated: {__import__('time').strftime('%Y-%m-%d %H:%M:%S')}",
        "",
        "## New Discovered Devices",
        f"Count: {len(new_devices)}",
        "",
    ]
    
    if new_devices:
        for device_id, info in sorted(new_devices.items()):
            lines.append(f"- `{device_id}`: type={info.get('type')}, filters={info.get('filters')}")
    else:
        lines.append("_No new devices discovered_")
    
    lines.extend([
        "",
        "## Conflicts (existing vs discovered)",
        f"Count: {len(conflicts)}",
        "",
    ])
    
    if conflicts:
        for conflict in conflicts:
            lines.append(f"- `{conflict['device_id']}`:")
            lines.append(f"  - existing: {conflict['existing']}")
            lines.append(f"  - discovered: {conflict['discovered']}")
    else:
        lines.append("_No conflicts_")
    
    lines.extend([
        "",
        "## Devices in devices.yml but not in Home Assistant",
        f"Count: {len(existing_missing)}",
        "",
    ])
    
    if existing_missing:
        for device_id in sorted(existing_missing):
            lines.append(f"- `{device_id}`")
    else:
        lines.append("_All devices found in HA_")
    
    lines.extend([
        "",
        "## Manual Actions Needed",
        "",
        "1. Review new devices - verify type and filters are correct",
        "2. Resolve conflicts - ensure device types match actual hardware",
        "3. Check missing devices - remove stale entries from devices.yml",
    ])
    
    summary = "\n".join(lines)
    
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    try:
        with open(output_path, "w") as f:
            f.write(summary)
        log.info(f"Autodiscovery: Wrote review summary to {output_path}")
    except Exception as e:
        log.warning(f"Autodiscovery: Failed to write summary: {e}")
    
    return summary


def run_full_discovery(
    devices_manual_path: str = "./pyscript/devices.yml",
    discovered_path: str = DEFAULT_DISCOVERED_PATH,
    summary_path: str = "./pyscript/debug/autodiscovery_review.md",
    hass_obj=None
) -> Dict:
    """
    Run full autodiscovery process.
    
    Args:
        hass_obj: Optional hass object. If provided, uses this directly.
    
    Returns merged device_defs for use by AreaTree.
    """
    log.info("Autodiscovery: Starting full discovery")
    
    # Use provided hass or fall back to module-level
    if hass_obj is not None:
        global hass
        hass = hass_obj
    
    discovered = discover_devices(hass_obj)
    
    if not discovered:
        log.warning("Autodiscovery: No devices discovered")
        return {}
    
    existing_discovered = load_existing_discovered(discovered_path)
    
    manual = {}
    if os.path.exists(devices_manual_path):
        try:
            with open(devices_manual_path, "r") as f:
                manual = yaml.safe_load(f) or {}
        except Exception as e:
            log.warning(f"Autodiscovery: Failed to load manual devices: {e}")
    
    merged, new_devices, updated, conflicts = merge_with_existing(
        discovered, existing_discovered, manual
    )
    
    write_discovered(existing_discovered, new_devices, discovered_path)
    
    ha_device_ids = set(discovered.keys())
    manual_ids = set(manual.keys())
    missing_from_ha = manual_ids - ha_device_ids
    
    summary = generate_review_summary(
        new_devices, conflicts, list(missing_from_ha), summary_path
    )
    
    log.info(f"Autodiscovery: Complete. Merged {len(merged)} devices, {len(new_devices)} new")
    
    discover_and_merge_layouts(discovered)
    
    merged_layout = merge_layouts(
        layout_manual_path="./pyscript/layout.yml",
        discovered_layout_path="./pyscript/discovered_layout.yml",
        merged_output_path="./pyscript/layout_merged.yml"
    )
    
    return merged


def discover_and_merge_layouts(
    discovered_devices: Dict,
    layout_manual_path: str = "./pyscript/layout.yml",
    discovered_layout_path: str = "./pyscript/discovered_layout.yml"
) -> Dict:
    """
    Discover areas from HA and generate layout additions.
    
    Returns area-to-device mappings that can be added to layout.yml.
    """
    if ha_device_registry is None:
        log.warning("Autodiscovery: HA device registry unavailable for layout discovery")
        return {}
    
    try:
        from area_tree import hass
    except ImportError:
        hass = None
    if hass is None:
        log.warning("Autodiscovery: hass object unavailable for layout discovery")
        return {}
    
    try:
        device_registry = ha_device_registry.async_get(hass)
        entity_registry = ha_entity_registry.async_get(hass)
    except Exception as e:
        log.warning(f"Autodiscovery: Failed to get registries for layout: {e}")
        return {}
    
    device_to_entity = {}
    for entity_id, entity in entity_registry.entities.items():
        if entity.device_id and not entity.disabled_by:
            if entity.domain in ["light", "cover", "switch", "media_player", "fan"]:
                if "." in entity_id:
                    _, object_id = entity_id.split(".", 1)
                    device_to_entity[entity.device_id] = object_id
    
    area_devices = {}
    for device_id, device in device_registry.devices.items():
        if not device.area_id:
            continue
        
        entity_id = device_to_entity.get(device_id)
        if not entity_id:
            continue
        
        area_name = device.area_id
        if area_name not in area_devices:
            area_devices[area_name] = []
        
        if entity_id not in area_devices[area_name]:
            area_devices[area_name].append(entity_id)
    
    if not area_devices:
        log.info("Autodiscovery: No area mappings found in HA")
        return {}
    
    os.makedirs(os.path.dirname(discovered_layout_path) or ".", exist_ok=True)
    
    existing_layout = {}
    if os.path.exists(discovered_layout_path):
        try:
            with open(discovered_layout_path, "r") as f:
                existing_layout = yaml.safe_load(f) or {}
        except Exception:
            pass
    
    merged_layout = OrderedDict()
    for area_name, devices in existing_layout.items():
        merged_layout[area_name] = devices
    
    new_area_devices = {}
    for area_name, devices in area_devices.items():
        if area_name not in merged_layout:
            new_area_devices[area_name] = devices
            merged_layout[area_name] = devices
        else:
            existing = set(merged_layout[area_name])
            for dev in devices:
                if dev not in existing:
                    merged_layout[area_name].append(dev)
    
    try:
        with open(discovered_layout_path, "w") as f:
            f.write("# Auto-generated area mappings from HA\n")
            f.write("# Add these to layout.yml or merge manually\n\n")
            ordered_dump(merged_layout, f)
        log.info(f"Autodiscovery: Wrote layout discoveries to {discovered_layout_path}")
    except Exception as e:
        log.warning(f"Autodiscovery: Failed to write layout: {e}")
    
    log.info(f"Autodiscovery: Layout discovery complete. Found {len(area_devices)} areas with devices")
    
    return area_devices


def merge_layouts(
    layout_manual_path: str = "./pyscript/layout.yml",
    discovered_layout_path: str = "./pyscript/discovered_layout.yml",
    merged_output_path: str = "./pyscript/layout_merged.yml"
) -> Dict:
    """
    Merge manual layout.yml with discovered_layout.yml.
    
    Returns the merged layout dict for direct use.
    """
    manual_layout = {}
    if os.path.exists(layout_manual_path):
        try:
            with open(layout_manual_path, "r") as f:
                manual_layout = yaml.safe_load(f) or {}
        except Exception as e:
            log.warning(f"Autodiscovery: Failed to load manual layout: {e}")
    
    discovered_layout = {}
    if os.path.exists(discovered_layout_path):
        try:
            with open(discovered_layout_path, "r") as f:
                discovered_layout = yaml.safe_load(f) or {}
        except Exception:
            pass
    
    if not discovered_layout:
        log.info("Autodiscovery: No discovered layout to merge")
        return manual_layout
    
    merged = OrderedDict()
    
    for area_name, area_data in manual_layout.items():
        merged[area_name] = area_data
    
    new_areas = {}
    for area_name, devices in discovered_layout.items():
        if area_name not in merged:
            new_areas[area_name] = {
                "outputs": devices if isinstance(devices, list) else []
            }
            merged[area_name] = new_areas[area_name]
            log.info(f"Autodiscovery: Added new area '{area_name}' from discovery")
        else:
            existing_outputs = merged[area_name].get("outputs", [])
            if isinstance(existing_outputs, list):
                existing_set = set(existing_outputs)
                for dev in devices:
                    if dev not in existing_set:
                        existing_outputs.append(dev)
                        log.info(f"Autodiscovery: Added device '{dev}' to area '{area_name}'")
                merged[area_name]["outputs"] = existing_outputs
    
    try:
        os.makedirs(os.path.dirname(merged_output_path) or ".", exist_ok=True)
        with open(merged_output_path, "w") as f:
            f.write("# Auto-merged layout (manual + discovered)\n")
            f.write("# Do not edit - regenerate from sources\n\n")
            yaml.dump(dict(merged), f, default_flow_style=False, sort_keys=False)
        log.info(f"Autodiscovery: Wrote merged layout to {merged_output_path}")
    except Exception as e:
        log.warning(f"Autodiscovery: Failed to write merged layout: {e}")
    
    log.info(f"Autodiscovery: Layout merge complete. {len(new_areas)} new areas added")
    
    return merged


def run_autodiscovery():
    """Service to manually trigger full autodiscovery."""
    try:
        from area_tree import load_config
    except ImportError:
        from area_tree import config_settings as load_config
    try:
        config = load_config()
    except:
        config = {"devices": "./pyscript/devices.yml"}
    
    merged = run_full_discovery(
        devices_manual_path=config.get("devices", "./pyscript/devices.yml"),
        discovered_path="./pyscript/discovered.yml",
        summary_path="./pyscript/debug/autodiscovery_review.md"
    )
    
    return {
        "devices_found": len(merged),
        "review_summary": "./pyscript/debug/autodiscovery_review.md"
    }


def get_discovered_summary():
    """Service to get the current discovery summary without re-running."""
    try:
        with open("./pyscript/debug/autodiscovery_review.md", "r") as f:
            return f.read()
    except Exception as e:
        return f"No summary available: {e}"
