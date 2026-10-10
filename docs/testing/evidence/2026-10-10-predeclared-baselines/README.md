# Evidencia: baselines emparejados del estudio predeclarado (2026-10-10)

Resultado y lectura: `docs/research/trend-pullback-predeclared-v1-baselines.md`.
Metodo: `docs/decisions/2026-10-10-predeclared-matched-baselines.md`.

Entradas: plan congelado y CSV extraidos de
`../2026-10-05-shared-pipeline/predeclared-3e9b4d4/complete-evidence.zip`
(`frozen-plan.json`, `inputs/*.csv`, `inputs/inputs.json`), sin modificar:

- `frozen-plan.json`: `6e10245a0ce90d3d044d3aebd60587c1a4c5e87f6485015279ae2b87878f4611` (igual al plan_id)
- `inputs/EURUSD_M5.csv`: `79446e07bc0ebec10eeeac7378a46b3289121ba441d5b68e5bf3019ed0483ac7`
- `inputs/GBPUSD_M5.csv`: `d60cdbd349d5e10dfc5fcc9ffc60fa75669171103ca596a5006e4485953a3cee`
- `inputs/USDJPY_M5.csv`: `3d00ce997b53a9f15a213de58cb0cb6eca9d5eca15a148287eeb4f1f446a1d1f`
- `inputs/inputs.json`: `ba8d926b41f5fc962558e35e06abb82b47ac496e9d4c20dfba70f418d003cd0e`

Codigo de baselines usado: commit `2fa174c` con el arbol limpio
(`baseline_code.git_dirty=false` en `baselines.json`); su `src/` y `scripts/`
son los de `8ec083f`, que anade la verificacion de paridad contra el evaluador:

- `src/python/agi_style_forex_bot_mt5/research/predeclared_baselines.py`: `b88dba6bddd738941cacaa45707d09472990bbd1de57a33eb28c5f6a87bcdbf7`
- `scripts/run_predeclared_baselines.py`: `2d19254320aefb4a8493279bad4e2d0cfbfbdf9ccf499a5953aea014774f1120`

Comando (Python 3.14.4, pandas 3.0.2, NumPy 2.4.4; 22 min 24 s):

```bash
python -B scripts/run_predeclared_baselines.py --source-root <repo> \
  --inputs inputs/inputs.json --plan frozen-plan.json --output baselines-run-8ec083f --replications 1000
```

Salidas: `baselines.json` (`b84a7a5321965174a025d63216dbc8e8f1f55bceb087318df4d61225b3d3a93f`),
`baselines.csv` (`09d74e5836035be08faba2f2d7df0fbeb1b605801a44ef8cf80d95f14a0214eb`) y `run.log`.
En las 27 celdas, `evaluate_trend_pullback` produjo los mismos trades, PnL neto,
win rate y drawdown que el subconjunto de la estrategia (si no, la celda habria
fallado). Frente a `summary.json` del estudio preservado, trades, win rate y
drawdown son identicos y PnL neto y PF difieren solo por el orden de suma en
coma flotante (maximo 1,8e-12). Flags `promotion_eligible`,
`execution_authorized`, `full_pipeline_verified` y `full_risk_pipeline_applied`
son false.

Una ejecucion previa del codigo sin esa verificacion (arbol de trabajo sobre
`0915dcb`) produjo un `baselines.json` identico salvo `baseline_code` y el
mismo `baselines.csv` byte a byte.
