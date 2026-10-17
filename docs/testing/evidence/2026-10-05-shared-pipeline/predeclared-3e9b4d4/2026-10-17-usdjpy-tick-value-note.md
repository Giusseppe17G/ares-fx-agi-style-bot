# Nota 2026-10-17: importes USD de USDJPY sobrestimados

Nota anadida despues de archivar esta evidencia. No modifica el protocolo
congelado (`docs/research/trend-pullback-predeclared-v1.md`) ni ningun archivo
de esta carpeta: `README.md`, `plan.json`, `summary.json`, `journal.jsonl`,
`manifest.json`, `archive-manifest.json` y `complete-evidence.zip` conservan sus
bytes y hashes. Decision: `docs/decisions/2026-10-17-derived-tick-value.md`.

La corrida uso la metadata de `assumed_fx_spec` con un tick value fijo de 1 USD
por tick y lote para los tres simbolos (`plan.json`: USDJPY `tick_size` 0.001,
`tick_value` 1.0). Es correcto para EURUSD y GBPUSD con contrato 100.000; para
USDJPY no. Un tick de 0,001 JPY sobre 100.000 USD son 100 JPY, es decir
`100 / precio` USD. Los cierres USDJPY archivados van de 152,319 a 160,703, asi
que el valor correcto estaba entre 0,622 y 0,657 USD. Los importes USD de las
nueve celdas USDJPY (PnL bruto, perdidas, drawdowns y riesgo) quedaron
sobrestimados unas 1,5 veces: entre 1,52 y 1,61 segun el precio.

La comision de 7 USD por lote es fija, asi que el PnL neto no se divide por el
mismo factor. En las nueve celdas USDJPY el PnL bruto antes de comision ya era
negativo: con el valor corregido el neto sigue negativo, con una perdida USD
algo menor, y el PF, el win rate y la R solo pueden ser iguales o menores.
Trades, decisiones y senales no cambian (lote fijo; la estrategia no lee el tick
value). EURUSD y GBPUSD no estan afectados. Ninguna conclusion del README
depende de ese valor: no habia ventaja y sigue sin haberla.

No se regenero. Las filas USDJPY de `README.md` y `summary.json`, y los
baselines emparejados de `docs/testing/evidence/2026-10-10-predeclared-baselines/`,
que reutilizan el mismo plan congelado, conservan los importes sobrestimados.
Volver a ejecutar `scripts/prepare_inspected_development_study.py` con el codigo
actual produce entradas distintas de las descritas en el protocolo (tick value
de USDJPY derivado del primer cierre); seria otra corrida, no esta reproduccion.
