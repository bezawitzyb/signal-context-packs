"""Config files load and hold the numbers the docs mirror (config wins)."""

import secrets

from ctxpack.config import Settings, load_yaml, mode_limits, model_for, sqlalchemy_url


def test_models_have_roles_and_prices():
    models = load_yaml("models")
    for role in ("reasoner", "worker", "evaluator", "synth"):
        name = model_for(role)
        assert name in models["prices_usd_per_mtok"]


def test_mode_limits():
    quick, standard = mode_limits("quick"), mode_limits("standard")
    assert quick["max_tool_calls"] == 15 and standard["max_tool_calls"] == 30
    assert quick["item_budget"] == 600 and standard["item_budget"] == 2000
    assert load_yaml("modes")["queue_max"] == 3


def test_confidence_weights_sum_to_one():
    weights = load_yaml("scoring")["confidence"]["weights"]
    assert abs(sum(weights.values()) - 1.0) < 1e-9


def test_secret_is_never_shown_in_repr():
    value = secrets.token_hex(12)  # random each run; no key ever in the code
    s = Settings(_env_file=None, **{"run_key": value})
    assert s.is_set("RUN_KEY")
    assert value not in repr(s)


def test_sqlalchemy_url():
    assert sqlalchemy_url("postgresql://u@h/db").startswith("postgresql+psycopg://")
    assert sqlalchemy_url("sqlite:///x.db") == "sqlite:///x.db"
