"""Predeclared daily FX study, trial ledger and runner on synthetic data (no real prices)."""
import json

import numpy as np
import pandas as pd
import pytest

from agi_style_forex_bot_mt5.research.daily_fx import runner
from agi_style_forex_bot_mt5.research.daily_fx.data import PricePanel
from agi_style_forex_bot_mt5.research.daily_fx.plans import G10_VS_USD, slow_premia_v1
from agi_style_forex_bot_mt5.research.daily_fx.portfolio import CostModel, PortfolioConfig, RiskLimits
from agi_style_forex_bot_mt5.research.daily_fx.study import (Acceptance, DataBinding, Hypothesis, StudyPlan,
    engine_sha256, hypotheses_from_grid, run_development, run_holdout)
from agi_style_forex_bot_mt5.research.trial_registry import TrialLedger

CURRENCIES = ("EUR", "JPY", "GBP", "CHF", "AUD", "CAD")
DIGEST = "a" * 64
# Generous invariants so a planted edge shows clearly in a short synthetic sample.
LIMITS = RiskLimits(risk_per_position=0.02, max_open_risk=0.2, max_net_usd_risk=None)
# Gates loosened for the planted-edge case: these tests check the plumbing, not the thresholds.
EASY = Acceptance(min_development_sharpe=0.3, max_development_pbo=1.0, max_currency_share=1.0,
                  max_development_drawdown=0.5, max_holdout_drawdown=0.5, max_promotion_pbo=1.0)


def _panel(drift_scale, seed):
    rng = np.random.default_rng(seed)
    index = pd.bdate_range("2000-01-03", periods=4200, tz="UTC")
    # Persistent regimes: the trend direction of each currency flips every ~2 years.
    regimes = np.repeat(rng.choice([-1.0, 1.0], size=(9, len(CURRENCIES))), 500, axis=0)[:len(index)]
    steps = rng.normal(0.0, 0.006, size=(len(index), len(CURRENCIES))) + drift_scale * regimes
    prices = pd.DataFrame(np.exp(np.cumsum(steps, axis=0)), index=index, columns=list(CURRENCIES))
    return PricePanel(prices, "synthetic", DIGEST)


def _plan(**overrides):
    primary = PortfolioConfig(lookbacks=(126,), rebalance_days=10)
    hypothesis = hypotheses_from_grid("H1_TSMOM", "trend", primary,
                                      {"lookbacks": [(63,), (252,)], "rebalance_days": [21]})
    values = dict(name="synthetic", currencies=CURRENCIES, development=("2001-01-01", "2010-12-31"),
                  holdout=("2011-01-01", "2016-12-31"), hypotheses=(hypothesis,),
                  costs=CostModel({code: 0.5 for code in CURRENCIES}, 20.0),
                  data=DataBinding("synthetic", DIGEST), limits=LIMITS, random_replicas=39,
                  pbo_blocks=8, spa_bootstraps=300, acceptance=EASY)
    values.update(overrides)
    return StudyPlan(**values)


def test_plan_hash_binds_parameters_data_and_engine():
    plan = _plan()
    assert plan.plan_hash() == _plan().plan_hash() and len(plan.plan_hash()) == 64
    assert plan.plan_hash() != _plan(random_replicas=41).plan_hash()
    assert plan.plan_hash() != _plan(acceptance=Acceptance()).plan_hash()
    assert plan.plan_hash() != _plan(data=DataBinding("synthetic", "b" * 64)).plan_hash()
    assert plan.plan_hash() != _plan(engine="c" * 64).plan_hash()
    assert plan.plan_hash() != _plan(runtime={"python": "0", "numpy": "0", "pandas": "0"}).plan_hash()
    assert plan.engine == engine_sha256() and len(plan.hypotheses[0].variants) == 3


def test_plan_validation_rejects_overlaps_controls_and_unbound_rates():
    with pytest.raises(ValueError):
        _plan(holdout=("2010-06-01", "2016-12-31")).validate()
    for control in (PortfolioConfig(signal="random"), PortfolioConfig(flip=True), PortfolioConfig(shift_days=300)):
        with pytest.raises(ValueError):
            _plan(hypotheses=(Hypothesis("H0", "control", control),)).validate()
    with pytest.raises(ValueError):
        _plan(hypotheses=(Hypothesis("H2", "carry", PortfolioConfig(signal="tscarry"), carry_accrual=True),)).validate()
    with pytest.raises(ValueError):
        _plan(hypotheses=(Hypothesis("H2", "carry", PortfolioConfig(signal="tscarry")),),
              data=DataBinding("synthetic", DIGEST, "d" * 64)).validate()
    with pytest.raises(ValueError, match="time-shifted"):
        _plan(hypotheses=(Hypothesis("H1", "trend", PortfolioConfig(), timing_claim=False),)).validate()


def test_runs_refuse_other_data_or_changed_engine(tmp_path):
    ledger = TrialLedger(tmp_path / "ledger.jsonl")
    panel = _panel(0.0, seed=2)
    with pytest.raises(ValueError, match="price data"):
        run_development(_plan(), PricePanel(panel.prices, "synthetic", "f" * 64), None, None, ledger)
    with pytest.raises(ValueError, match="engine"):
        run_development(_plan(engine="c" * 64), panel, None, None, ledger)
    with pytest.raises(ValueError, match="version"):
        run_development(_plan(runtime={"python": "0", "numpy": "0", "pandas": "0"}), panel, None, None, ledger)
    assert not ledger.path.exists()


def test_development_never_sees_holdout_data(tmp_path):
    plan = _plan()
    panel = _panel(0.0012, seed=1)
    first = run_development(plan, panel, None, None, TrialLedger(tmp_path / "a.jsonl"))
    altered = panel.prices.copy()
    altered.loc["2011-01-01":] *= 1.5
    second = run_development(plan, PricePanel(altered, "synthetic", DIGEST), None, None,
                             TrialLedger(tmp_path / "b.jsonl"))
    assert first["hypotheses"] == second["hypotheses"] and first["data"]["last_day"] <= "2010-12-31"


def test_a_planted_trend_passes_development_and_the_holdout_exactly_once(tmp_path):
    plan = _plan()
    panel = _panel(0.0012, seed=1)
    ledger = TrialLedger(tmp_path / "ledger.jsonl")
    development = run_development(plan, panel, None, None, ledger)
    result = development["hypotheses"][0]
    assert result["proceed_to_holdout"], result["checks"]
    assert result["random_control"]["quota"] < 0.05 and result["shift_control"]["quota"] < 0.05
    assert result["flipped_sharpe"] < 0 and development["trials"] == 4
    assert development["execution_authorized"] is False
    assert ledger.count("development_trial") == 4 and ledger.count("development_controls") == 1
    with pytest.raises(ValueError, match="already run"):
        run_development(plan, panel, None, None, ledger)
    holdout = run_holdout(plan, panel, None, None, development, ledger, tmp_path / "holdout.json")
    assert holdout["hypotheses"][0]["verdict"] == "PASSED_RESEARCH"
    assert json.loads((tmp_path / "holdout.json").read_text())["plan_hash"] == plan.plan_hash()
    # A second scoring is refused by the ledger, whatever the output path.
    with pytest.raises(ValueError, match="exactly once"):
        run_holdout(plan, panel, None, None, development, ledger, tmp_path / "other.json")
    recorded = [record for record in ledger.records() if record["kind"] == "holdout"]
    assert len(recorded) == 1 and recorded[0]["payload"]["hypotheses"][0]["verdict"] == "PASSED_RESEARCH"


def test_random_walks_are_rejected_at_development(tmp_path):
    plan = _plan(acceptance=Acceptance())
    panel = _panel(0.0, seed=2)
    ledger = TrialLedger(tmp_path / "ledger.jsonl")
    development = run_development(plan, panel, None, None, ledger)
    assert not development["hypotheses"][0]["proceed_to_holdout"]
    holdout = run_holdout(plan, panel, None, None, development, ledger, tmp_path / "holdout.json")
    assert holdout["hypotheses"][0] == {"hypothesis_id": "H1_TSMOM", "evaluated": False, "verdict": "REJECTED",
                                        "reason": "failed development gates"}


def test_holdout_refuses_results_from_another_plan_or_without_a_ledgered_development(tmp_path):
    plan = _plan()
    panel = _panel(0.0012, seed=1)
    ledger = TrialLedger(tmp_path / "ledger.jsonl")
    development = run_development(plan, panel, None, None, ledger)
    with pytest.raises(ValueError):
        run_holdout(_plan(random_replicas=41), panel, None, None, development, ledger, tmp_path / "h.json")
    with pytest.raises(ValueError, match="ledger"):
        run_holdout(plan, panel, None, None, development, TrialLedger(tmp_path / "empty.jsonl"), tmp_path / "h.json")


def test_ledger_detects_tampering(tmp_path):
    ledger = TrialLedger(tmp_path / "ledger.jsonl")
    ledger.append("development_trial", "p" * 64, {"trial": "H1:0", "sharpe": 0.1})
    ledger.append("development_trial", "p" * 64, {"trial": "H1:1", "sharpe": 0.2})
    assert ledger.count("development_trial") == 2 and ledger.has("development_trial", "p" * 64)
    lines = ledger.path.read_text(encoding="utf-8").splitlines()
    ledger.path.write_text(lines[0].replace("0.1", "0.9") + "\n" + lines[1] + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="chain broken"):
        list(ledger.records())
    ledger.path.write_text(lines[1] + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="chain broken"):
        ledger.count("development_trial")


def test_slow_premia_plan_is_valid_and_declares_seven_trials():
    plan = slow_premia_v1(DIGEST, "e" * 64)
    plan.validate()
    assert plan.currencies == G10_VS_USD and sum(len(item.configs()) for item in plan.hypotheses) == 7
    assert plan.limits == RiskLimits() and plan.limits.max_positions == 10 and plan.limits.max_open_risk == 0.05
    assert plan.development[1] < plan.holdout[0]
    assert [item.timing_claim for item in plan.hypotheses] == [True, True, False]


def test_runner_freezes_once_and_refuses_a_plan_that_no_longer_matches(tmp_path, monkeypatch):
    panel = PricePanel(_panel(0.0, seed=3).prices.reindex(columns=list(CURRENCIES)), "fred_h10_daily", DIGEST)
    built = {}

    def fake_plan(args):
        plan = slow_premia_v1(DIGEST, built.get("rates", "e" * 64))
        return plan, panel, None, "e" * 64

    monkeypatch.setattr(runner, "_plan", fake_plan)
    plan_file = tmp_path / "plan.json"
    base = ["--prices", "p.csv", "--rates", "r.csv", "--plan-file", str(plan_file)]
    assert runner.main(["freeze", *base]) == 0
    frozen = json.loads(plan_file.read_text(encoding="utf-8"))
    assert frozen["plan_hash"] == slow_premia_v1(DIGEST, "e" * 64).plan_hash()
    assert runner.main(["freeze", *base]) == 2  # never overwritten
    built["rates"] = "f" * 64  # the data changed after freezing
    assert runner.main(["development", *base, "--ledger", str(tmp_path / "l.jsonl")]) == 2
    assert not (tmp_path / "development.json").exists() and not (tmp_path / "l.jsonl").exists()


def test_holdout_follows_the_ledger_not_an_edited_development_file(tmp_path):
    plan = _plan(acceptance=Acceptance())
    panel = _panel(0.0, seed=2)
    ledger = TrialLedger(tmp_path / "ledger.jsonl")
    development = run_development(plan, panel, None, None, ledger)
    assert development["hypotheses"][0]["proceed_to_holdout"] is False
    forged = json.loads(json.dumps(development, default=float))
    forged["hypotheses"][0]["proceed_to_holdout"] = True
    forged["pbo"]["pbo"] = 0.0
    with pytest.raises(ValueError, match="differ from what the ledger recorded"):
        run_holdout(plan, panel, None, None, forged, ledger, tmp_path / "holdout.json")
    dropped = json.loads(json.dumps(development, default=float))
    dropped["hypotheses"] = []
    with pytest.raises(ValueError, match="ledger"):
        run_holdout(plan, panel, None, None, dropped, ledger, tmp_path / "holdout.json")
    # The genuine file round-tripped through JSON is accepted.
    stored = json.loads(json.dumps(development, default=float))
    holdout = run_holdout(plan, panel, None, None, stored, ledger, tmp_path / "holdout.json")
    assert [item["verdict"] for item in holdout["hypotheses"]] == ["REJECTED"]


def test_another_plan_cannot_reuse_a_scored_holdout_or_developed_dates(tmp_path):
    panel = _panel(0.0012, seed=1)
    ledger = TrialLedger(tmp_path / "ledger.jsonl")
    plan = _plan()
    run_holdout(plan, panel, None, None, run_development(plan, panel, None, None, ledger), ledger, tmp_path / "a.json")
    tweaked = _plan(cost_stress_factor=2.0000001)
    with pytest.raises(ValueError, match="overlap a holdout already scored"):
        run_development(tweaked, panel, None, None, ledger)
    # A plan whose development covers another plan's holdout dates blocks that holdout.
    other = TrialLedger(tmp_path / "other.jsonl")
    late = _plan(development=("2001-01-01", "2012-12-31"), holdout=("2013-01-01", "2016-12-31"))
    run_development(late, panel, None, None, other)
    early = _plan(name="early")
    early_dev = run_development(early, panel, None, None, other)
    with pytest.raises(ValueError, match="already developed on these holdout dates"):
        run_holdout(early, panel, None, None, early_dev, other, tmp_path / "b.json")


def test_trial_sharpes_use_each_trial_window(tmp_path):
    plan = _plan()
    development = run_development(plan, _panel(0.0012, seed=1), None, None, TrialLedger(tmp_path / "l.jsonl"))
    assert development["hypotheses"][0]["deflated_sharpe"]["trials"] == 4
    checks = development["hypotheses"][0]["checks"]
    assert all(type(value) is bool for value in checks.values())
