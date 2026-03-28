#!/usr/bin/env python3
"""
Sync Home Assistant status to Obsidian vault.

Usage:
    python3 sync_ha_status.py
    python3 sync_ha_status.py --source periodic
    python3 sync_ha_status.py --source event
    python3 sync_ha_status.py --dry-run
"""

import argparse
import os
import re
import sys
import json
from datetime import datetime
import json as json_module

try:
    import requests
except ImportError:
    print("ERROR: requests library not installed")
    sys.exit(1)

VAULT_ROOT = os.getenv("VAULT_ROOT", "/vault")
STATUS_NOTE = os.path.join(VAULT_ROOT, "Areas/Home/Homeassistant/Status.md")
HA_URL = os.getenv("HA_URL", "http://localhost:8123")
HA_TOKEN = os.getenv("HA_TOKEN")

DRY_RUN = False


def get_ha_status():
    """Fetch status from Home Assistant API."""
    headers = {"Authorization": f"Bearer {HA_TOKEN}"}
    
    if not HA_TOKEN:
        print("ERROR: HA_TOKEN environment variable not set")
        sys.exit(1)
    
    try:
        resp_config = requests.get(f"{HA_URL}/api/config", headers=headers, timeout=10)
        config = json_module.loads(resp_config.text)
        
        resp_states = requests.get(f"{HA_URL}/api/states", headers=headers, timeout=10)
        states = json_module.loads(resp_states.text)
        
        resp_automations = requests.get(f"{HA_URL}/api/automations", headers=headers, timeout=10)
        automations = json_module.loads(resp_automations.text) if resp_automations.status_code == 200 else []
        
        resp_services = requests.get(f"{HA_URL}/api/services", headers=headers, timeout=10)
        services = json_module.loads(resp_services.text) if resp_services.status_code == 200 else {}
    except json_module.JSONDecodeError as e:
        print(f"ERROR: JSON decode failed: {e}")
        print(f"Config response status: {resp_config.status_code}")
        print(f"Config response text: {resp_config.text[:200]}")
        sys.exit(1)
    except requests.exceptions.RequestException as e:
        print(f"ERROR: Failed to connect to HA: {e}")
        sys.exit(1)
    
    return {
        "ha_version": config.get("version", "unknown"),
        "uptime": config.get("uptime", "unknown"),
        "location_name": config.get("location_name", "Home"),
        "states": states,
        "automations": automations,
        "services": services,
    }


def calculate_uptime(config):
    """Calculate uptime from config/state."""
    try:
        import datetime
        import pytz
        import time
        
        if config.get("uptime"):
            seconds = config["uptime"]
            days = int(seconds // 86400)
            hours = int((seconds % 86400) // 3600)
            minutes = int((seconds % 3600) // 60)
            if days > 0:
                return f"{days}d {hours}h {minutes}m"
            elif hours > 0:
                return f"{hours}h {minutes}m"
            else:
                return f"{minutes}m"
        
        state_resp = requests.get(f"{HA_URL}/api/states", headers={"Authorization": f"Bearer {HA_TOKEN}"}, timeout=10)
        states = json_module.loads(state_resp.text)
        for s in states:
            if s["entity_id"] in ("sensor.last_boot", "sensor.home_assistant_last_boot"):
                last_boot = s["state"]
                if last_boot and last_boot != "unknown":
                    dt = datetime.datetime.fromisoformat(last_boot.replace("Z", "+00:00"))
                    now = datetime.datetime.now(pytz.UTC)
                    delta = now - dt
                    hours = int(delta.total_seconds() // 3600)
                    minutes = int((delta.total_seconds() % 3600) // 60)
                    return f"{hours}h {minutes}m"
        return "running"
    except Exception:
        return "running"


def update_note(status, source="manual"):
    """Update the Obsidian status note with HA data."""
    if not os.path.exists(STATUS_NOTE):
        print(f"ERROR: Status note not found at {STATUS_NOTE}", file=sys.stderr)
        sys.exit(1)
    
    with open(STATUS_NOTE, "r") as f:
        content = f.read()
    
    states = status["states"]
    
    light_on = len([s for s in states if s["entity_id"].startswith("light") and s["state"] == "on"])
    entity_count = len(states)
    tracker_online = len([s for s in states if s["entity_id"].startswith("device_tracker") and s["state"] == "home"])
    
    automations = status["automations"]
    automations_enabled = sum(1 for a in automations if a.get("enabled", False))
    automations_disabled = len(automations) - automations_enabled
    
    services = status["services"]
    if isinstance(services, dict):
        pyscript_services = len(services.get("pyscript", []))
    else:
        pyscript_services = 0
    pyscript_status = "OK" if pyscript_services > 0 else "Warning: No pyscript services"
    
    recent = sorted(
        [s for s in states if not s["entity_id"].startswith("sensor.")],
        key=lambda x: x.get("last_changed", ""),
        reverse=True
    )[:8]
    
    recent_events = "\n".join([
        f"- **{s['entity_id']}**: {s['state']} ({s['last_changed'][:16]})" 
        for s in recent
    ])
    if not recent_events:
        recent_events = "_No recent events_"
    
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    uptime = calculate_uptime(status.get("config", {}))
    
    replacements = {
        "ha_version": status["ha_version"],
        "uptime": uptime,
        "pyscript_status": f"{pyscript_status} ({pyscript_services} services)",
        "entity_count": str(entity_count),
        "lights_on": str(light_on),
        "trackers_online": str(tracker_online),
        "automations_enabled": str(automations_enabled),
        "automations_disabled": str(automations_disabled),
        "recent_events": recent_events,
        "timestamp": timestamp,
        "sync_method": source,
    }
    
    for key, value in replacements.items():
        begin_marker = f"<!-- automation-managed:begin:{key} -->"
        end_marker = f"<!-- automation-managed:end:{key} -->"
        pattern = f"({re.escape(begin_marker)}).*?({re.escape(end_marker)})"
        
        def replacer(match):
            return f"{match.group(1)}\n  {value}\n  {match.group(2)}"
        
        content = re.sub(pattern, replacer, content, flags=re.DOTALL)
    
    content = re.sub(
        r'\*\*Updated:\*\* \d{4}-\d{2}-\d{2}',
        f"**Updated:** {datetime.now().strftime('%Y-%m-%d')}",
        content
    )
    
    if DRY_RUN:
        print("=== DRY RUN - Would update with: ===")
        for key, value in replacements.items():
            print(f"  {key}: {value}")
        print(f"=== End dry run ===")
        return
    
    with open(STATUS_NOTE, "w") as f:
        f.write(content)
    
    print(f"Updated status at {timestamp} (source: {source})")


def main():
    global DRY_RUN
    
    parser = argparse.ArgumentParser(description="Sync HA status to Obsidian")
    parser.add_argument("--source", default="manual", choices=["manual", "periodic", "event"],
                        help="Source of the sync")
    parser.add_argument("--dry-run", action="store_true", help="Print updates without writing")
    args = parser.parse_args()
    
    DRY_RUN = args.dry_run
    
    status = get_ha_status()
    update_note(status, source=args.source)


if __name__ == "__main__":
    main()
