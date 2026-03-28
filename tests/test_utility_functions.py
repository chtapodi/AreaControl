"""Tests for utility functions: combine_colors, expand_args, get_state_similarity."""
import types
import sys
import copy
import pytest

from .conftest import load_area_tree as _base_load
import os


def load_area_tree():
    if 'homeassistant' not in sys.modules:
        sys.modules['homeassistant'] = types.ModuleType('homeassistant')
    if 'homeassistant.util' not in sys.modules:
        util_mod = types.ModuleType('homeassistant.util')
        util_mod.color = types.SimpleNamespace(
            color_RGB_to_hs=lambda r, g, b: (0, 0),
            color_hs_to_RGB=lambda h, s: (0, 0, 0),
            color_temperature_to_rgb=lambda k: (0, 0, 0),
        )
        sys.modules['homeassistant.util'] = util_mod
    return _base_load(use_real_drivers=os.getenv('AREATREE_REAL_DRIVERS') == '1')


@pytest.fixture
def area_tree():
    return load_area_tree()


# -- combine_colors tests --

class TestCombineColors:
    def test_add_basic(self, area_tree):
        result = area_tree.combine_colors([100, 50, 25], [50, 100, 75])
        assert result == [150, 150, 100]

    def test_add_clamps_to_255(self, area_tree):
        result = area_tree.combine_colors([200, 200, 200], [200, 200, 200])
        assert result == [255, 255, 255]

    def test_add_zeros(self, area_tree):
        result = area_tree.combine_colors([0, 0, 0], [0, 0, 0])
        assert result == [0, 0, 0]

    def test_average_basic(self, area_tree):
        result = area_tree.combine_colors([100, 200, 50], [200, 100, 150], strategy="average")
        assert result == [150.0, 150.0, 100.0]

    def test_average_preserves_order(self, area_tree):
        """Verify each channel is independently averaged (regression for index bug)."""
        result = area_tree.combine_colors([255, 0, 0], [0, 255, 0], strategy="average")
        assert result[0] == pytest.approx(127.5)
        assert result[1] == pytest.approx(127.5)
        assert result[2] == pytest.approx(0.0)

    def test_add_preserves_channel_independence(self, area_tree):
        """Each channel should be the sum of inputs, not swapped (regression for index bug)."""
        result = area_tree.combine_colors([10, 20, 30], [1, 2, 3])
        assert result == [11, 22, 33]

    def test_clamps_negatives_to_zero(self, area_tree):
        """Negative values should be clamped to 0."""
        result = area_tree.combine_colors([-10, 0, 0], [0, 0, 0])
        assert result == [0, 0, 0]


# -- get_state_similarity tests --

class TestGetStateSimilarity:
    def test_identical_states(self, area_tree):
        s = {"status": 1, "brightness": 255, "rgb_color": [255, 0, 0]}
        assert area_tree.get_state_similarity(s, s) == pytest.approx(1.0)

    def test_completely_different_states(self, area_tree):
        s1 = {"status": 1, "brightness": 255}
        s2 = {"status": 0, "brightness": 100}
        result = area_tree.get_state_similarity(s1, s2)
        assert result < 1.0

    def test_empty_vs_populated(self, area_tree):
        """Similarity between empty and populated state should be 0."""
        s1 = {}
        s2 = {"status": 1, "brightness": 255}
        result = area_tree.get_state_similarity(s1, s2)
        assert result == pytest.approx(0.0)

    def test_no_shared_keys(self, area_tree):
        s1 = {"brightness": 255}
        s2 = {"rgb_color": [255, 0, 0]}
        result = area_tree.get_state_similarity(s1, s2)
        assert result == pytest.approx(0.0)

    def test_partial_match(self, area_tree):
        s1 = {"status": 1, "brightness": 255}
        s2 = {"status": 1, "brightness": 100}
        result = area_tree.get_state_similarity(s1, s2)
        assert 0.0 < result < 1.0

    def test_list_values_compared_elementwise(self, area_tree):
        s1 = {"rgb_color": [255, 0, 0]}
        s2 = {"rgb_color": [255, 0, 0]}
        assert area_tree.get_state_similarity(s1, s2) == pytest.approx(1.0)

    def test_type_mismatch_handled(self, area_tree):
        """Mismatched types for same key should not crash (regression for self-comparison bug)."""
        s1 = {"brightness": 255}
        s2 = {"brightness": "high"}
        # Should not raise, just reduce similarity
        result = area_tree.get_state_similarity(s1, s2)
        assert isinstance(result, float)


# -- expand_args tests --

class TestExpandArgs:
    def _make_event_manager(self, area_tree):
        """Create a minimal EventManager for testing expand_args."""
        em = area_tree.EventManager.__new__(area_tree.EventManager)
        return em

    def test_expands_state_variable(self, area_tree):
        em = self._make_event_manager(area_tree)
        state = {"status": 1, "brightness": 255}
        result = em.expand_args(["$state"], {}, state)
        assert result == [state]

    def test_preserves_non_variable_args(self, area_tree):
        em = self._make_event_manager(area_tree)
        result = em.expand_args(["hello", 42, None], {}, {})
        assert result == ["hello", 42, None]

    def test_does_not_mutate_original(self, area_tree):
        """Regression: old code mutated the input list."""
        em = self._make_event_manager(area_tree)
        original = ["$state", "other"]
        original_copy = list(original)
        em.expand_args(original, {}, {"status": 1})
        assert original == original_copy

    def test_unknown_dollar_variable_preserved(self, area_tree):
        em = self._make_event_manager(area_tree)
        result = em.expand_args(["$unknown"], {}, {})
        assert result == ["$unknown"]

    def test_empty_args(self, area_tree):
        em = self._make_event_manager(area_tree)
        result = em.expand_args([], {}, {"status": 1})
        assert result == []

    def test_multiple_state_expansions(self, area_tree):
        em = self._make_event_manager(area_tree)
        state = {"brightness": 100}
        result = em.expand_args(["$state", "middle", "$state"], {}, state)
        assert result == [state, "middle", state]
