# PyScript Operations, Reload Safety, And Verification

## When To Read

- Validating any PyScript code change
- Changing reload paths, startup behavior, services, or operational wiring
- Debugging silent automation failures, especially motion or power sensors

## Critical Rules

- Motion sensors and power sensors are always-on infrastructure. Treat trigger-pipeline changes as production-risk work.
- Never call `homeassistant.reload_config_entry` for PyScript.
- Never call `init()` as a reload mechanism.
- Never change `reset()` to call `init()`.
- `@task_unique` must remain on `_delayed_off()` inside `schedule_motion_off()`.

## Reload Safety Hierarchy

- Safe: `pyscript.reload()`
- Safe: saving a `.py` file so the watcher triggers the same reload path
- Safe: full Home Assistant restart
- Broken: `homeassistant.reload_config_entry`
- Broken: calling `init()` directly from `reset()` or any service-call context

## Debugging And Observability

- Expected successful rule flow: incoming event debug log -> tag or guard pass -> scope resolution -> combined state output -> `logger.info("apply-state", ...)`.
- Common failures:
  - no rule matched the trigger prefix or tags
  - guard function returned `False`
  - driver `filter_state` dropped unsupported keys
  - merge produced a no-op because the delta was below a driver threshold
- Quick health checks:
  - confirm rule-referenced device ids exist
  - verify area membership and graph paths
  - inspect frozen areas if writes appear ignored

## Required Post-Change Verification

- After every PyScript code change, check trigger health:

```sh
docker logs homeassistant --since="5m" 2>&1 | grep "TRIGGER:"
```

- If no `TRIGGER:` lines appear after a known sensor state change, recover immediately:

```sh
TOKEN=$(grep HA_TOKEN /home/mango/docker/homeassistant/pyscript/.env | cut -d'"' -f2) && \
  docker exec homeassistant curl -s -X POST "http://localhost:8123/api/services/homeassistant/restart" \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" -d '{}'
```

- Confirm triggers re-registered after restart:

```sh
docker logs homeassistant --since="2m" 2>&1 | grep "generating state trigger.*motion"
```

## Deployment Checklist

- If any reload was triggered, confirm it used `pyscript.reload()` or file save.
- If `_delayed_off()` was touched, confirm the `@task_unique` decorator is still present by explicit search.
- Verify the changed rule or service evaluates without exceptions.
- Do not claim validation that you did not actually perform.

## References

- `pyscript/AGENTS.md`
- `pyscript/references/architecture.md`
- `pyscript/references/config-and-extension.md`
