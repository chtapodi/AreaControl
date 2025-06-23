import pytest
from .conftest import load_area_tree


def test_summarize_state_nested_dicts():
    area_tree = load_area_tree()
    state = {
        "outer1": {"values": {"brightness": 50, "rgb_color": [100, 150, 200]}},
        "outer2": {"values": {"brightness": 150, "rgb_color": [200, 50, 100]}}
    }
    result = area_tree.summarize_state(state)
    assert result["brightness"] == pytest.approx(100.0)
    assert result["rgb_color"] == pytest.approx([150.0, 100.0, 150.0])


def test_combine_colors_modes():
    area_tree = load_area_tree()
    add_result = area_tree.combine_colors([10, 20, 30], [40, 50, 60], "add")
    avg_result = area_tree.combine_colors([10, 20, 30], [40, 50, 60], "average")
    assert add_result == [50, 70, 90]
    assert avg_result == pytest.approx([25.0, 35.0, 45.0])


def test_calibrate_rgb_factors():
    area_tree = load_area_tree()
    result = area_tree.calibrate_rgb([100, 150, 200], [0.5, 1.5, 2.0])
    assert result == [50, 225, 255]
