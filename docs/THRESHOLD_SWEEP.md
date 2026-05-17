# Threshold Sweep

Threshold sweep evaluates controlled setup-score and component-score combinations to find where the system begins producing enough research candidates.

It is not profit optimization and it does not authorize demo/live execution.

## Command

```powershell
$env:PYTHONPATH="src/python"
py -m agi_style_forex_bot_mt5.cli --mode threshold-sweep --symbols EURUSD,GBPUSD,USDJPY,USDCAD,USDCHF,AUDUSD,EURJPY,NZDUSD --data-dir data\historical --report-dir data\reports\calibration --profiles CONSERVATIVE,BALANCED,ACTIVE,RESEARCH_ONLY
```

## Swept Values

- `min_setup_score`: 50, 55, 60, 65, 70, 75
- `min_component_score`: 40, 50, 60
- `cost_fit_min`: 40, 50, 60, 70
- `structure_fit_min`: 40, 50, 60, 70
- `volatility_fit_min`: 40, 50, 60, 70
- `session_fit_min`: 40, 50, 60, 70
- `ensemble_min_score`: 50, 55, 60, 65, 70

## Outputs

- `threshold_sweep_summary.json`
- `threshold_sweep.csv`
- `config_suggestions/*.ini`

## Guardrails

Sweep suggestions never bypass:

- max spread
- stale tick rejection
- market closed rejection
- broker `NOT_READY`
- risk gate
- ML rejection outside research-only diagnostics
- portfolio guard outside diagnostics

`ACTIVE` and `RESEARCH_ONLY` configs are explicitly marked `NOT FOR DEMO/LIVE EXECUTION`.
