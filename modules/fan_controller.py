"""
fan_controller.py — Temperature-driven fan control for area_tree.

Integrates as a pyscript module, imported at runtime by area_tree.py.
Uses @time_trigger for periodic evaluation, state.get() for sensor reads,
and switch.turn_on/switch.turn_off for direct fan control.

Loads configuration from fan_config.yml (enhanced with per-fan mapping).
"""

# --- Configuration ---
# Defaults — overridden by fan_config.yml
CONFIG_DEFAULTS = {
    "goal_temp": 68,
    "hysteresis_up": 2,
    "hysteresis_down": 1,
    "pre_cool_target": 64,
    "pre_cool_threshold": 90,
    "outdoor_cool_margin": 3,
    "outdoor_hot_margin": 5,
    "hold_duration_minutes": 60,
}

# Temperature sensor registry — loaded from temp_sensors.yml
TEMP_SENSORS = {}  # {room_name: [{entity_id, weight, offset}, ...]}

# Fan registry — loaded from fan_config.yml fans: section
FAN_REGISTRY = {}  # {fan_name: {entity_id, room, priority, label, also_cools: []}}

# Runtime state
_config = {}  # merged config (defaults + per_area overrides)
_pre_cool_active = False
_fan_holds = {}  # {fan_name: expiry_timestamp}
_last_decisions = {}  # {fan_name: {state, reason, timestamp}}
_initialized = False


def load_fan_config():
    """Load fan_config.yml and temp_sensors.yml. Called once from init()."""
    global _config, TEMP_SENSORS, FAN_REGISTRY, _initialized

    # Load fan_config.yml
    try:
        cfg = load_yaml("./pyscript/fan_config.yml") or {}
    except Exception:
        log.warning("fan_controller: Could not load fan_config.yml, using defaults")
        cfg = {}

    defaults = dict(CONFIG_DEFAULTS)
    defaults.update(cfg.get("defaults", {}))
    _config = {"defaults": defaults, "per_area": cfg.get("per_area", {})}

    # Load fan registry
    FAN_REGISTRY = cfg.get("fans", {})
    log.info(f"fan_controller: Loaded {len(FAN_REGISTRY)} fans from config")
    for fname, finfo in FAN_REGISTRY.items():
        log.info(f"fan_controller:   {fname} -> {finfo.get('entity_id')} ({finfo.get('room')})")

    # Load temp sensors
    try:
        sensor_cfg = load_yaml("./pyscript/temp_sensors.yml") or {}
        for s in sensor_cfg.get("sensors", []):
            room = s.get("room")
            if room not in TEMP_SENSORS:
                TEMP_SENSORS[room] = []
            TEMP_SENSORS[room].append(s)
    except Exception:
        log.warning("fan_controller: Could not load temp_sensors.yml")
    log.info(f"fan_controller: Loaded temp sensors for {len(TEMP_SENSORS)} rooms")
    for room, sensors in TEMP_SENSORS.items():
        log.info(f"fan_controller:   {room}: {len(sensors)} sensors")

    _initialized = True


def get_room_config(room_name):
    """Get merged config for a room (defaults + per_area override)."""
    cfg = dict(_config.get("defaults", CONFIG_DEFAULTS))
    per_area = _config.get("per_area", {})
    if room_name in per_area:
        cfg.update(per_area[room_name])
    return cfg


def get_room_temperature(room_name):
    """Calculate weighted average temperature for a room."""
    sensors = TEMP_SENSORS.get(room_name, [])
    if not sensors:
        return None

    temps = []
    total_weight = 0
    for s in sensors:
        try:
            raw = state.get(s["entity_id"])
        except Exception:
            continue
        if raw is None or str(raw).lower() in ("none", "unavailable", "unknown"):
            continue
        try:
            corrected = float(raw) - s.get("offset", 0)
            temps.append((corrected, s.get("weight", 0.5)))
            total_weight += s.get("weight", 0.5)
        except (ValueError, TypeError):
            continue

    if not temps or total_weight == 0:
        return None
    return sum(t * w for t, w in temps) / total_weight


def get_outdoor_temp():
    """Get current outdoor temperature from met.no forecast."""
    try:
        w = state.get("weather.forecast_met_no")
    except Exception:
        return None
    if w is None:
        return None
    try:
        return float(w.attributes.get("temperature", 0))
    except Exception:
        return None


def get_tomorrow_max_temp():
    """Get max temperature from next 24h forecast."""
    try:
        f = state.get("sensor.home_hourly_forecast_2")
    except Exception:
        return None
    if f is None:
        return None
    try:
        temps = [h.get("temperature") for h in f.attributes.get("forecast", [])[:24]
                 if h.get("temperature") is not None]
        return max(temps) if temps else None
    except Exception:
        return None


def check_pre_cool():
    """Evaluate pre-cool mode based on tomorrow's forecast."""
    global _pre_cool_active
    tomorrow_max = get_tomorrow_max_temp()
    if tomorrow_max is None:
        return

    threshold = _config.get("defaults", CONFIG_DEFAULTS).get("pre_cool_threshold", 90)
    if tomorrow_max >= threshold and not _pre_cool_active:
        _pre_cool_active = True
        log.info(
            f"fan_controller: PRECOOL ACTIVE — tomorrow max {tomorrow_max}°F >= {threshold}°F, "
            f"lowering target to {_config['defaults'].get('pre_cool_target', 64)}°F"
        )
    elif tomorrow_max < threshold and _pre_cool_active:
        _pre_cool_active = False
        log.info(
            f"fan_controller: PRECOOL INACTIVE — tomorrow max {tomorrow_max}°F < {threshold}°F"
        )


def detect_manual_overrides():
    """Detect manual fan toggles and set 60-minute holds."""
    hold_minutes = _config.get("defaults", CONFIG_DEFAULTS).get("hold_duration_minutes", 60)
    now = time.time()

    for fan_name, fan_info in FAN_REGISTRY.items():
        entity_id = fan_info["entity_id"]
        try:
            current_state = state.get(entity_id)
        except Exception:
            current_state = None
        if current_state is None:
            continue

        current_on = str(current_state).lower() in ("on", "true", "1")
        last_decision = _last_decisions.get(fan_name, {})
        last_decision_state = last_decision.get("state")

        if last_decision_state is not None and current_on != last_decision_state:
            # User toggled — set hold
            _fan_holds[fan_name] = now + (hold_minutes * 60)
            log.info(
                f"fan_controller: Manual override detected for {fan_name} "
                f"(decision={last_decision_state}, actual={current_on}) "
                f"— hold for {hold_minutes} min"
            )


def evaluate_fan(fan_name, fan_info):
    """Evaluate and actuate a single fan."""
    entity_id = fan_info["entity_id"]
    room = fan_info["room"]
    also_cools = fan_info.get("also_cools", [])

    # 1. Manual hold check
    now = time.time()
    hold_expiry = _fan_holds.get(fan_name)
    if hold_expiry is not None:
        if now < hold_expiry:
            remaining = int((hold_expiry - now) / 60)
            _last_decisions[fan_name] = {
                "state": None,
                "reason": f"manual_hold_{remaining}m",
                "timestamp": now,
            }
            return  # Skip — user manually controlled
        else:
            # Hold expired
            del _fan_holds[fan_name]
            log.info(f"fan_controller: Hold expired for {fan_name}, resuming control")

    # 2. Get current fan state
    try:
        current_ha = state.get(entity_id)
    except Exception:
        current_ha = None
    current_on = str(current_ha).lower() in ("on", "true", "1") if current_ha is not None else False

    # 3. Get room temperature
    room_temp = get_room_temperature(room)
    if room_temp is None:
        log.warning(f"fan_controller: No temp data for room '{room}', skipping {fan_name}")
        return

    # Also check adjacent rooms if this fan cools them
    for adj_room in also_cools:
        adj_temp = get_room_temperature(adj_room)
        if adj_temp is not None:
            # Use the warmest temperature among covered rooms
            room_temp = max(room_temp, adj_temp)

    # 4. Get outdoor temperature
    outdoor_temp = get_outdoor_temp()

    # 5. Get room config
    room_config = get_room_config(room)

    # 6. Determine active goal (pre-cool override)
    if _pre_cool_active:
        active_goal = room_config.get("pre_cool_target", room_config["goal_temp"])
    else:
        active_goal = room_config["goal_temp"]

    hysteresis_up = room_config["hysteresis_up"]
    hysteresis_down = room_config["hysteresis_down"]
    outdoor_cool_margin = room_config.get("outdoor_cool_margin",
                                          CONFIG_DEFAULTS["outdoor_cool_margin"])
    outdoor_hot_margin = room_config.get("outdoor_hot_margin",
                                         CONFIG_DEFAULTS["outdoor_hot_margin"])

    # 7. Outdoor gate
    outdoor_too_hot = (
        outdoor_temp is not None
        and outdoor_temp > room_temp + outdoor_hot_margin
    )
    outdoor_not_cool = (
        outdoor_temp is not None
        and outdoor_temp >= room_temp - outdoor_cool_margin
    )

    # 8. Decision
    target_on = None
    reason = None

    if outdoor_too_hot:
        target_on = False
        reason = "outdoor_hot"
    elif outdoor_not_cool and current_on:
        # Outdoor is still warm — if fan is on, turn it off
        # Don't turn on if it's off (that would be wasteful)
        target_on = False
        reason = "outdoor_warm"
    elif room_temp >= active_goal + hysteresis_up:
        target_on = True
        reason = "too_hot"
    elif room_temp <= active_goal - hysteresis_down:
        target_on = False
        reason = "cool_enough"
    # Else: in hysteresis band — no change

    # 9. Apply decision
    if target_on is not None and target_on != current_on:
        try:
            if target_on:
                switch.turn_on(entity_id=entity_id)
                log.info(
                    f"fan_controller: ON  {fan_name} ({entity_id}) — {reason} "
                    f"(room={room_temp:.1f}°F, goal={active_goal}°F, "
                    f"outdoor={outdoor_temp})"
                )
            else:
                switch.turn_off(entity_id=entity_id)
                log.info(
                    f"fan_controller: OFF {fan_name} ({entity_id}) — {reason} "
                    f"(room={room_temp:.1f}°F, goal={active_goal}°F, "
                    f"outdoor={outdoor_temp})"
                )
        except Exception as e:
            log.warning(f"fan_controller: Failed to set {fan_name}: {e}")

    # Record decision for manual override detection
    if target_on is not None:
        _last_decisions[fan_name] = {
            "state": target_on,
            "reason": reason,
            "timestamp": now,
        }


@time_trigger("cron(*/2 * * * *)")
def fan_controller_periodic():
    """Main fan controller loop — runs every 2 minutes."""
    global _fan_holds, _pre_cool_active

    if not _initialized:
        log.warning("fan_controller: Not initialized yet, skipping cycle")
        return

    # Clear expired holds
    now = time.time()
    _fan_holds = {k: v for k, v in _fan_holds.items() if v > now}

    # Pre-cool check
    check_pre_cool()

    # Detect manual overrides
    detect_manual_overrides()

    # Evaluate each fan (sorted for deterministic order)
    for fan_name in sorted(FAN_REGISTRY.keys()):
        try:
            evaluate_fan(fan_name, FAN_REGISTRY[fan_name])
        except Exception as e:
            log.warning(f"fan_controller: Error evaluating {fan_name}: {e}")

    # Log active fans summary
    active_fans = []
    for fan_name, fan_info in FAN_REGISTRY.items():
        try:
            s = state.get(fan_info["entity_id"])
            if str(s).lower() in ("on", "true", "1"):
                active_fans.append(fan_name)
        except Exception:
            pass
    if active_fans:
        log.info(f"fan_controller: Active fans: {', '.join(active_fans)}")


# Diagnostic service — can be called manually to check state
@service
def fan_controller_status():
    """Print current fan controller status to logs."""
    if not _initialized:
        log.info("fan_controller: NOT INITIALIZED")
        return

    log.info("=== FAN CONTROLLER STATUS ===")
    log.info(f"Pre-cool active: {_pre_cool_active}")
    log.info(f"Fans configured: {len(FAN_REGISTRY)}")
    log.info(f"Active holds: {len(_fan_holds)}")

    for fan_name, fan_info in sorted(FAN_REGISTRY.items()):
        entity_id = fan_info["entity_id"]
        try:
            s = state.get(entity_id)
        except Exception:
            s = "ERROR"
        room_temp = get_room_temperature(fan_info["room"])
        room_config = get_room_config(fan_info["room"])
        active_goal = room_config.get("pre_cool_target", room_config["goal_temp"]) if _pre_cool_active else room_config["goal_temp"]

        hold_info = ""
        hold_expiry = _fan_holds.get(fan_name)
        if hold_expiry:
            remaining = int((hold_expiry - time.time()) / 60)
            hold_info = f" [HOLD {remaining}m]"

        last_dec = _last_decisions.get(fan_name, {})
        dec_info = f" last_decision={last_dec.get('state')} ({last_dec.get('reason')})" if last_dec else ""

        log.info(
            f"  {fan_name}: state={s} temp={room_temp:.1f}°F "
            f"goal={active_goal}°F{hold_info}{dec_info}"
        )
    log.info("=== END FAN CONTROLLER STATUS ===")
