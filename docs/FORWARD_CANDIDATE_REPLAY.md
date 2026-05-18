# Forward Candidate Replay

Phase 31 adds a research-only replay layer for blocked BALANCED_STABLE forward candidates. It is used after `forward-signal-diagnose` shows that live data and features are ready, but candidates are still blocked by context such as `REGIME_MISMATCH` or `ENSEMBLE_SCORE_LOW`.

## Why Replay First

Do not edit thresholds directly from a few live cycles. A blocked forward candidate may be correctly rejected because the live regime, session, spread or setup quality does not match the stable backtest context. Replay turns those blocks into auditable evidence before any future research variant is proposed.

## Commands

```powershell
$env:PYTHONPATH="src/python"
py -m agi_style_forex_bot_mt5.cli --mode forward-candidate-replay --sqlite data\sqlite\forward-shadow-stable.sqlite3 --log-dir data\logs\forward-shadow-stable --diagnostics-dir data\reports\forward_diagnostics --profile-config data\reports\stability_repair\balanced_stable.ini --output-dir data\reports\forward_research
```

```powershell
py -m agi_style_forex_bot_mt5.cli --mode forward-blocker-sensitivity --diagnostics-dir data\reports\forward_diagnostics --profile-config data\reports\stability_repair\balanced_stable.ini --output-dir data\reports\forward_research
```

## Reports

- `candidate_replay_summary.json`
- `candidate_replay.csv`
- `regime_mismatch_analysis.json`
- `ensemble_score_analysis.json`
- `blocker_sensitivity.json`
- `blocker_sensitivity.csv`
- `research_variants.csv`
- `report.html`

## Replay Decisions

- `BLOCK_CORRECT`: current stable filters or thresholds did their job.
- `BLOCK_TOO_STRICT_RESEARCH_ONLY`: worth testing in offline research only.
- `DATA_INCOMPLETE`: candidate metadata is not sufficient for analysis.
- `FEATURE_INCONSISTENT`: feature/runtime blockers still need repair.
- `NEEDS_MORE_FORWARD_CANDIDATES`: not enough evidence yet.

## Sensitivity Variants

The variants are diagnostic only:

- `KEEP_CURRENT_BALANCED_STABLE`
- `IGNORE_REGIME_BLOCK_RESEARCH`
- `RELAX_ENSEMBLE_SCORE_5`
- `RELAX_ENSEMBLE_SCORE_10`
- `RELAX_REGIME_AND_SCORE_5`

Every variant is marked `research_only=true` and `not_for_demo_live=true`. None modifies the running forward-shadow process, SQLite paper trades, BALANCED_STABLE config, risk limits, demo/live settings or MT5 execution adapters.

If a variant looks promising, the next safe step is a future `BALANCED_STABLE_V2` research profile with backtest, robustness and paper-shadow gates. It is not a live trading approval.
