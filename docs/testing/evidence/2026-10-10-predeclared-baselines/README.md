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

Codigo de baselines usado (bytes del arbol de trabajo sobre `0915dcb`, que
`baselines.json` registra como `baseline_code`; el commit que conserva esta
evidencia contiene los mismos bytes):

- `src/python/agi_style_forex_bot_mt5/research/predeclared_baselines.py`: `afe9e86dc0656027112b04cbc4affca4484628477f087721411a7804193f90cc`
- `scripts/run_predeclared_baselines.py`: `08a489f48b1d1f29cd3903563756330ca2d568b2033b5e5454ae316d0bf0d46c`

Comando (Python 3.14.4, pandas 3.0.2, NumPy 2.4.4; 13 min 23 s):

```bash
python -B scripts/run_predeclared_baselines.py --source-root <repo> \
  --inputs inputs/inputs.json --plan frozen-plan.json --output baselines-run --replications 1000
```

Salidas: `baselines.json` (`1baec2dfa21eb99cd2d1e6daece3b7f2567776dd2e4fe59c3ed0a275f16bb4bc`),
`baselines.csv` (`09d74e5836035be08faba2f2d7df0fbeb1b605801a44ef8cf80d95f14a0214eb`) y `run.log`.
Las 27 celdas de la estrategia coinciden exactamente con `summary.json` del
estudio preservado. Flags `promotion_eligible`, `execution_authorized`,
`full_pipeline_verified` y `full_risk_pipeline_applied` son false.
