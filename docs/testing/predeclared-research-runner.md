# Runner offline predeclarado: entrada y verificación

El runner está en `research/predeclared_runner.py`; la CLI separada es
`scripts/run_predeclared_research.py`. No lee modelos, credenciales o cuentas.
Solo usa los archivos nombrados por el estudio y las fuentes del checkout.

## Entrada explícita

El JSON de estudio exige exactamente estas claves superiores:
`data_role`, `denomination_currency`, `initial_balance`, `lot`, `random_seed`,
`management` y `datasets`.

- `data_role`: `SYNTHETIC_FIXTURE` o
  `DEVELOPMENT_DIAGNOSTIC_ALREADY_INSPECTED`.
- `denomination_currency`: moneda declarada del capital, tick value y comisión;
  no se deduce de EURUSD/USDJPY ni se convierte moneda implícitamente.
- `management`: los cinco campos de `ResearchManagement`, incluido
  `max_holding_bars`, suministrados explícitamente.
- `datasets`: objeto por EURUSD/GBPUSD/USDJPY. Cada entrada exige `path`,
  `provider`, `quality_report`, `tick_value_currency`, `tick_value_status`,
  `instrument`, `cost_model` y `cost_provenance`.
- `instrument`: todos los campos de `InstrumentSpec` (currency_margin puede
  omitirse). No se inventa metadata por nombre del símbolo.
- `cost_model`: los siete campos de `CostModel`, incluidos point, tick_size,
  tick_value, spread_points, slippage_points, comisión y máximo spread. Deben
  coincidir con la geometría del instrumento.
- `cost_provenance`: source, assumptions (lista), commission_currency,
  swap_mode y status. Estados y swap_mode siguen la validación del plan.

El CSV exige siete columnas únicas: `timestamp_utc`, `open`, `high`, `low`,
`close`, `volume`, `spread_points`. No ordena filas ni infiere zonas horarias.
Los paths relativos se resuelven respecto al JSON, independientemente de CWD.
El hash del archivo se calcula al leerlo; no se acepta un valor inventado en su
lugar. La calidad y procedencia declaradas permanecen afirmaciones del proveedor.

Para el historico local ya inspeccionado existe un conversor separado,
`scripts/prepare_inspected_development_study.py`. Recibe source-root, data-dir y
output-dir explicitos y exige los tres CSV M5 del formato exportado. Usa los
mismos bytes para parsear y calcular hash de origen; verifica que time y
timestamp_utc coincidan, preserva todas las filas/precios/spreads y comprueba
roundtrip de la salida canonica. No repara ceros ni huecos. Crea un directorio
nuevo y JSON con los supuestos ilustrativos fijados en el protocolo, incluidos
moneda USD, tick value supuesto, lote 0.1 y costes. Nunca evalua resultados ni
etiqueta esa historia como holdout. Sus seis pruebas verifican preservacion,
fallos temporales y ausencia de sobrescritura.

## Ejecución

Congelar fuentes antes de preparar el plan y usar procesos nuevos:

```powershell
py -3.14 -B scripts/run_predeclared_research.py --source-root . plan --inputs study.json --output frozen-plan.json
py -3.14 -B scripts/run_predeclared_research.py --source-root . run --inputs study.json --plan frozen-plan.json --output new-study-run
```

`plan` no evalúa estrategia ni resultados; persiste la hipótesis y bindings.
`run` exige que el estudio reconstruido coincida exactamente con ese plan.
No reutiliza un directorio existente. Código de salida 2 indica rechazo o
comparación incompleta; 0 significa ejecución de software completada, no edge
financiero ni promoción.

La salida conserva plan, descripción de inputs, manifest, journal,
`cells/<id>.json`, decisiones y trades JSONL por celda y summary. Un archivo de
plan sin summary no es una corrida completada. Las métricas de cada tramo
permanecen separadas, con moneda y estado de profit factor. Los indicadores de
baselines, walk-forward y holdout no ejecutados permanecen explícitos.

La confirmación de plan/inputs/manifest/celda compara los bytes releídos con los
escritos. Los JSONL hacen flush/fsync y conservan un hash leído del archivo;
no se declara una segunda validación semántica de su contenido ni una
comparación con un digest calculado durante la escritura.

## Pruebas

```powershell
py -3.14 -B -m pytest tests/python/test_predeclared_research_runner.py tests/python/test_predeclared_research_review.py tests/python/test_trend_pullback_research_evaluator.py -q
```

Fixtures aisladas comprueban persistencia antes del evaluator real, matriz
completa, resultados reproducibles, métricas propias de cada split, ausencia de
sobrescritura, hashes de código/frame/archivo, mutaciones durante una corrida,
fallos de escritura, JSON estricto y CLI desde otra CWD. La fixture principal de
runner tiene train sin decisiones elegibles y development_test con operaciones
simuladas; copiar métricas de train no satisface la prueba.

Las pruebas no ejecutan el estudio sobre datos de mercado. Una fixture sintética
con beneficios/pérdidas solo verifica el software; no valida la hipótesis, el
coste histórico, el tick value ni la rentabilidad del sistema.

Persistencia: plan, inputs, manifest y celda comparan bytes escritos con lectura
posterior. JSONL de decisiones/trades usa flush, fsync y hash de contenido leido;
no implementa una segunda comparacion semantica fila por fila contra memoria.
El journal durable es un registro de progreso; solo summary completo acredita
que el runner termino, sin que ello implique suficiencia financiera.
