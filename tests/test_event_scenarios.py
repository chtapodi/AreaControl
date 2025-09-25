from pathlib import Path

import pytest

from tests.helpers.event_scenarios import load_scenario, run_event_scenario

SCENARIO_DIR = Path(__file__).parent / "service_scenarios"
SCENARIO_PATHS = sorted(SCENARIO_DIR.glob("*.yml"))


@pytest.mark.parametrize("scenario_path", SCENARIO_PATHS, ids=lambda path: path.stem)
def test_service_scenarios(load_service_area_tree, scenario_path):
    module = load_service_area_tree()
    scenario = load_scenario(scenario_path)
    run_event_scenario(module, scenario)
