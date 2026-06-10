"""Model cost multipliers and token cost calculation."""

MODEL_MULTIPLIERS: dict[str, float] = {
    "gpt-4o": 1.0,
    "gpt-4o-mini": 0.25,
    "gpt-4-turbo": 2.0,
    "gpt-3.5-turbo": 0.1,
    "claude-3-5-sonnet": 1.0,
    "claude-3-5-haiku": 0.25,
    "claude-3-opus": 3.0,
    "claude-3-sonnet": 1.0,
    "claude-3-haiku": 0.25,
    "claude-sonnet-4-6": 1.0,
    "claude-opus-4-8": 3.0,
    "claude-haiku-4-5": 0.25,
}

DEFAULT_MULTIPLIER = 1.0


def get_multiplier(model_id: str) -> float:
    return MODEL_MULTIPLIERS.get(model_id, DEFAULT_MULTIPLIER)


def calculate_cost(input_tokens: int, output_tokens: int, model_id: str) -> float:
    multiplier = get_multiplier(model_id)
    return (input_tokens + output_tokens) * multiplier
