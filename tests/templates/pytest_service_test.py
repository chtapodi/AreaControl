"""Pytest skeleton for new service scenarios.

Copy this file alongside your scenario YAML and adjust the glob if you want a
specialized suite. The shared ``tests/test_event_scenarios.py`` already
auto-discovers ``tests/service_scenarios/*.yml``, so most contributors only need
to drop a new YAML file.
"""

from pathlib import Path

import pytest

from tests.helpers.event_scenarios import load_scenario, run_event_scenario

SCENARIO_DIR = Path(__file__).parent / "service_scenarios"
SCENARIOS = sorted(SCENARIO_DIR.glob("*.yml"))


@pytest.mark.parametrize("scenario_path", SCENARIOS, ids=lambda path: path.stem)
def test_custom_service_scenarios(load_service_area_tree, scenario_path):
    module = load_service_area_tree()
    scenario = load_scenario(scenario_path)
    run_event_scenario(module, scenario)
