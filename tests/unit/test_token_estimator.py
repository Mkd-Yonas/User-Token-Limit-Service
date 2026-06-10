import pytest
from app.utils.token_estimator import calculate_cost, get_multiplier


def test_gpt4o_baseline():
    assert get_multiplier("gpt-4o") == 1.0


def test_gpt4o_mini_quarter():
    assert get_multiplier("gpt-4o-mini") == 0.25


def test_claude_opus_3x():
    assert get_multiplier("claude-3-opus") == 3.0


def test_unknown_model_defaults_to_1():
    assert get_multiplier("unknown-model-xyz") == 1.0


def test_calculate_cost_gpt4o():
    assert calculate_cost(1000, 500, "gpt-4o") == 1500.0


def test_calculate_cost_mini():
    assert calculate_cost(1000, 500, "gpt-4o-mini") == pytest.approx(375.0)


def test_calculate_cost_opus():
    assert calculate_cost(1000, 500, "claude-3-opus") == pytest.approx(4500.0)
