from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Iterable

import yaml


def load_scenario(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    data.setdefault("name", path.stem)
    data["path"] = path
    return data


def _assert_device_expectations(tree, expectations, scenario_name):
    for device_name, expected_state in expectations.items():
        device = tree.get_device(device_name)
        assert device is not None, f"{scenario_name}: device {device_name} missing"
        cache = device.cached_state or {}
        for key, expected_value in expected_state.items():
            if key == "locked":
                assert device.locked is expected_value, (
                    f"{scenario_name}: expected {device_name} locked={expected_value}"
                )
                continue
            actual_value = cache.get(key)
            assert (
                actual_value == expected_value
            ), f"{scenario_name}: {device_name} {key}={actual_value} != {expected_value}"


def _assert_area_expectations(tree, expectations, scenario_name):
    for area_name, expected_state in expectations.items():
        area = tree.get_area(area_name)
        assert area is not None, f"{scenario_name}: area {area_name} missing"
        if "frozen" in expected_state:
            frozen_expected = expected_state["frozen"]
            assert area.is_frozen() is frozen_expected, (
                f"{scenario_name}: expected {area_name} frozen={frozen_expected}"
            )
        state_expectations = {
            k: v for k, v in expected_state.items() if k != "frozen"
        }
        if state_expectations:
            state = area.get_state()
            for key, expected_value in state_expectations.items():
                actual_value = state.get(key)
                assert (
                    actual_value == expected_value
                ), f"{scenario_name}: {area_name} {key}={actual_value} != {expected_value}"


def _assert_service_expectations(module, expectations, scenario_name):
    for service_name, expected_calls in expectations.items():
        stub = getattr(module, service_name, None)
        assert stub is not None, f"{scenario_name}: service {service_name} missing"
        calls: Iterable[tuple[str, Dict[str, Any]]] = getattr(stub, "calls", [])
        calls = list(calls)
        assert len(calls) == len(expected_calls), (
            f"{scenario_name}: service {service_name} expected {len(expected_calls)} calls"
            f" but saw {len(calls)}"
        )
        for actual, expected in zip(calls, expected_calls):
            action, kwargs = actual
            exp_action = expected.get("action")
            if exp_action is not None:
                assert action == exp_action, (
                    f"{scenario_name}: service {service_name} action {action}"
                    f" != {exp_action}"
                )
            for key, value in expected.items():
                if key == "action":
                    continue
                assert kwargs.get(key) == value, (
                    f"{scenario_name}: service {service_name} expected {key}={value}"
                    f" but saw {kwargs.get(key)}"
                )


def run_event_scenario(module, scenario: Dict[str, Any]) -> None:
    scenario_name = scenario.get("name", "scenario")
    steps = scenario.get("steps", [])
    module.reset()
    tree = module.get_area_tree()

    for step in steps:
        if "call" in step:
            action = step["call"]
            kwargs = step.get("kwargs") or {}
            if not hasattr(module, action):
                raise AttributeError(f"{scenario_name}: unknown action {action}")
            getattr(module, action)(**kwargs)
            if action in {"init", "reset"}:
                tree = module.get_area_tree()
        elif "expect" in step:
            if tree is None:
                tree = module.get_area_tree()
            expectations = step["expect"]
            if "devices" in expectations:
                _assert_device_expectations(
                    tree, expectations["devices"], scenario_name
                )
            if "areas" in expectations:
                _assert_area_expectations(tree, expectations["areas"], scenario_name)
            if "services" in expectations:
                _assert_service_expectations(
                    module, expectations["services"], scenario_name
                )
        else:
            raise ValueError(f"{scenario_name}: unknown step {step}")
