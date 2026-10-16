"""Predeclared daily FX study runner on synthetic panels (no real prices)."""
import json

import numpy as np
import pandas as pd
import pytest

from agi_style_forex_bot_mt5.research.daily_fx.data import PricePanel
from agi_style_forex_bot_mt5.research.daily_fx.portfolio import CostModel, PortfolioConfig
from agi_style_forex_bot_mt5.research.daily_fx.study import (Acceptance, Hypothesis, StudyPlan, hypotheses_from_grid,
    run_development, run_holdout)

CURRENCIES = ("EUR", "JPY", "GBP", "CHF", "AUD", "CAD")


def _panel(drift_scale, seed):
    rng = np.random.default_rng(seed)
    index = pd.bdate_range("2000-01-03", periods=4200, tz="UTC")
    # Persistent regimes: the trend direction of each currency flips every ~2 years.
    regimes = np.repeat(rng.choice([-1.0, 1.0], size=(9, len(CURRENCIES))), 500, axis=0)[:len(index)]
    steps = rng.normal(0.0, 0.006, size=(len(index), len(CURRENCIES))) + drift_scale * regimes
    prices = pd.DataFrame(np.exp(np.cumsum(steps, axis=0)), index=index, columns=list(CURRENCIES))
    return PricePanel(prices, "synthetic", "0" * 64)


def _plan(**overrides):
    primary = PortfolioConfig(lookbacks=(63, 126, 252))
    hypothesis = hypotheses_from_grid("H1_TSMOM", "trend", primary,
                                      {"lookbacks": [(126, 252), (252,)], "rebalance_days": [1, 21]})
    values = dict(name="synthetic", currencies=CURRENCIES, development=("2001-01-01", "2010-12-31"),
                  holdout=("2011-01-01", "2016-12-31"), hypotheses=(hypothesis,),
                  costs=CostModel({code: 0.5 for code in CURRENCIES}, 50.0), random_replicas=40,
                  pbo_blocks=8, spa_bootstraps=300)
    values.update(overrides)
    return StudyPlan(**values)


def test_plan_hash_is_stable_and_covers_every_parameter():
    plan = _plan()
    assert plan.plan_hash() == _plan().plan_hash() and len(plan.plan_hash()) == 64
    assert plan.plan_hash() != _plan(random_replicas=41).plan_hash()
    assert plan.plan_hash() != _plan(acceptance=Acceptance(min_holdout_psr=0.8)).plan_hash()
    assert len(plan.hypotheses[0].variants) == 4


def test_plan_validation_rejects_overlaps_and_controls():
    with pytest.raises(ValueError):
        _plan(holdout=("2010-06-01", "2016-12-31")).validate()
    control = Hypothesis("H0", "random", PortfolioConfig(signal="random"))
    with pytest.raises(ValueError):
        _plan(hypotheses=(control,)).validate()


def test_a_planted_trend_passes_development_and_the_holdout_once(tmp_path):
    plan = _plan()
    panel = _panel(0.0012, seed=1)
    development = run_development(plan, panel)
    result = development["hypotheses"][0]
    assert result["proceed_to_holdout"], result["checks"]
    assert result["random_control"]["quota"] < 0.05 and result["flipped_sharpe"] < 0
    assert development["trials"] == 5 and development["execution_authorized"] is False
    output = tmp_path / "holdout.json"
    holdout = run_holdout(plan, panel, development, output)
    assert holdout["hypotheses"][0]["passed"] and json.loads(output.read_text())["plan_hash"] == plan.plan_hash()
    with pytest.raises(FileExistsError):
        run_holdout(plan, panel, development, output)


def test_random_walks_stop_at_development_and_skip_the_holdout(tmp_path):
    plan = _plan()
    panel = _panel(0.0, seed=2)
    development = run_development(plan, panel)
    assert not development["hypotheses"][0]["proceed_to_holdout"]
    holdout = run_holdout(plan, panel, development, tmp_path / "holdout.json")
    assert holdout["hypotheses"][0]["evaluated"] is False


def test_holdout_refuses_results_from_another_plan(tmp_path):
    plan = _plan()
    development = run_development(plan, _panel(0.0012, seed=1))
    with pytest.raises(ValueError):
        run_holdout(_plan(random_replicas=41), _panel(0.0012, seed=1), development, tmp_path / "h.json")
