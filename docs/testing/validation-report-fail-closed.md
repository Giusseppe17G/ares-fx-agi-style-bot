# Verificacion del master validation report 2.0

El reporte es una consolidacion de investigacion. No es una autorizacion de
demo/live ni una prueba de paridad completa. Cada export incluye los flags
execution_enabled=False, full_pipeline_verified=False y
promotion_authorized=False en JSON; HTML explica el mismo alcance. CSV mantiene
section/classification/available y agrega evidence_status/reason.

Fuentes y etiquetas admitidas, inspeccionadas en los productores del repositorio:

| Seccion | Etiquetas reconocidas |
|---|---|
| data_quality / broker_cost_profile | OK, WATCHLIST, REJECTED |
| walk_forward | APPROVED_FOR_SHADOW_OBSERVATION, WATCHLIST, REJECTED |
| monte_carlo / stress | las anteriores y LOW_SAMPLE_WARNING -> WATCHLIST |
| benchmark | las tres clasificaciones base y NEEDS_MORE_DATA -> WATCHLIST |
| competitive_scorecard | COMPETITIVE_CANDIDATE, NEEDS_OPTIMIZATION, WEAK_EDGE, REJECTED, NEEDS_MORE_DATA |
| broker_quality | EXECUTION_READY_SHADOW_ONLY, WATCHLIST, NOT_READY |
| readiness | CONTINUE_FORWARD_SHADOW, NEEDS_MORE_DATA, NEEDS_BROKER_FIX |
| research | las tres clasificaciones base |
| execution_simulation | CALIBRATED_OK, NEEDS_MORE_FORWARD_DATA, COST_ASSUMPTION_TOO_LOW |
| paper_vs_backtest | las anteriores, BACKTEST_TOO_OPTIMISTIC, STRATEGY_BEHAVIOR_DRIFT |

Las etiquetas nominales de otros workflows, como MONTE_CARLO_OK de robustness
fast, no se interpretan como equivalentes si aparecen en estos paths. En
readiness, classification y decision pueden representar el mismo resultado;
si ambas existen y difieren, la evidencia es invalida. Forward no inventa una
etiqueta de aprobacion: paper_report produce metricas, cuyos contadores total,
open y closed deben ser enteros no negativos, coherentes y contener observaciones.

Backtest se clasifica desde sus cuatro metricas con los umbrales existentes,
sin sustituir Infinity y sin tratar cero como ausencia. Las etiquetas propias
de backtester OK/WARNING_NO_SIGNALS/WARNING_NO_TRADES/WARNING_SIGNALS_NO_TRADES
son reconocidas; un warning impide la clasificacion favorable.

Las listas de mix y registry son artefactos informativos reales. No se les aplica
un contrato ficticio de objeto JSON; se valida la lista no vacia y la identidad
minima de sus filas, preservando el contenido original. Esto no certifica los
candidatos ni sus recomendaciones de riesgo.

Ejecutar sin MT5 ni datos productivos:

```powershell
py -3.14 -B -m pytest tests/python/test_validation_report_fail_closed.py tests/python/test_backtesting.py tests/python/test_phase6_pipeline.py tests/python/test_phase10_broker_quality.py
```

Cobertura: omision individual de las 16 fuentes; clasificaciones desconocidas o
con tipos invalidos; JSON scalar/lista en secciones objeto; duplicates anidados;
NaN, Infinity y overflow; valores numericos strings/bools/null; campos faltantes;
DD cero, firmado y limites exactos; warning de muestra reducida; indices vacios
o mal formados; contadores forward inconsistentes; fuentes ilegibles;
contradicciones de readiness; persistencia concordante JSON/CSV/HTML y scopes.
El fixture legacy conserva integracion completa del escritor y ahora declara las
cinco fuentes que nunca estuvieron disponibles.

Limite: AVAILABLE significa que la seccion se pudo consumir para consolidacion,
no que sus etiquetas, metricas o procedencia hayan sido verificadas de forma
independiente. Un source reconocido REJECTED tambien tiene evidencia disponible.
Los archivos invalidos/desconocidos se excluyen de summaries y su motivo queda
en evidence_quality. No se borra ni sobrescribe la evidencia de entrada.
