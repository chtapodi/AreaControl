# Testing Guide

The repository ships with helpers that let you exercise the pyscript services in
full without needing a running Home Assistant instance. The tests now support
both a **stubbed** mode (default) and an optional **real driver** mode gated by
an environment variable.

## Quick start

Run the full stubbed suite with:

```bash
pytest
```

The stubbed mode automatically patches the Home Assistant APIs, tracker
interfaces and YAML paths so tests use the deterministic fixtures in
`tests/fixtures/pyscript/`.

To opt into the real Home Assistant drivers, set the
`AREATREE_REAL_DRIVERS=1` environment variable and select the `ha_integration`
marker:

```bash
AREATREE_REAL_DRIVERS=1 pytest -m ha_integration
```

If the environment variable is not present the tests marked with
`ha_integration` are skipped. The real-driver workflow reuses the same fixture
YAML while loading the genuine driver implementations, so the assertions stay
stable.

## Service fixtures

`tests/conftest.py` exposes a `load_service_area_tree` fixture. It returns a
callable you can invoke inside tests:

```python
module = load_service_area_tree()                  # Stubbed drivers
module = load_service_area_tree(use_real_drivers=True)  # Requires AREATREE_REAL_DRIVERS=1
```

The fixture redirects `area_tree.load_yaml` to the test fixtures, provides stub
tracker classes, and ensures essential Home Assistant modules (like
`light`/`state`) exist so service calls do not raise exceptions. When real
drivers are requested the fixture skips automatically unless
`AREATREE_REAL_DRIVERS=1` is set.

## Scenario runner

Multi-step service flows live under `tests/service_scenarios/`. Each YAML file
is parsed by `tests/helpers/event_scenarios.py`, which offers:

- `load_scenario(path)` – parse a YAML file into a Python dict.
- `run_event_scenario(module, scenario)` – execute the listed service calls and
  assert on device/area expectations.

The shared test `tests/test_event_scenarios.py` auto-discovers every
`*.yml` file in `tests/service_scenarios/` and executes it. Add a new scenario by
copying the template in `tests/templates/service_scenario.yml`, updating the
steps, and saving it next to the others. Expectations support
`devices:<id>:<state>` (including `locked`), `areas:<name>:<state>` entries, and
`services:<name>` call logs. The stubbed `light` service stores a `calls` list so
you can assert emitted actions and `entity_id` values. Use the `frozen` key
under an area expectation to assert freeze status.

## Contributor templates

The `tests/templates/` directory contains ready-to-use skeletons:

- `service_scenario.yml` – blueprint for authoring a scenario YAML file.
- `pytest_service_test.py` – optional pytest skeleton if you need a bespoke test
  module. Most contributors can rely on the shared auto-discovery test instead.

Reference these templates from new documentation or pull requests so other
contributors can quickly bootstrap scenario coverage.
