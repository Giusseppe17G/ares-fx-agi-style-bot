# Estado verificable del bot: 2026-10-05

**Investigacion y paper; no preparado para ejecucion broker.** La estrategia
no ha superado el Strategy Promotion Gate. No existe evidencia que permita
llamarlo el mejor bot ni prometer una tasa de acierto o rentabilidad.

La implementacion actual corrige problemas que invalidaban conclusiones
anteriores. Se conserva ese historial y se distingue de la evidencia nueva.

## Implementado

- Features causales compartidas, direcciones en scoring y thresholds efectivos
  iguales en forward y backtest. No se bajaron umbrales para obtener trades.
- Nucleo comun con riesgo, ML, ranking, portfolio, asignacion de riesgo y limites
  paper. Registra aceptaciones, rechazos y fallos; datos desconocidos bloquean.
- Libro paper persistido: equity realizado/flotante, exposicion completa,
  referencias diarias y halt. PnL usa una sola vez el lotaje aprobado.
- Riesgo posterior al fill incluye slippage de salida, comision y tick grid.
  Redondeo de lotaje hacia abajo y protecciones obligatorias. No promete que un
  gap de mercado respete el presupuesto teorico de stop.
- Replay de decisiones registradas y nuevo replay cronologico con quotes
  explicitos. Este ultimo mantiene posiciones y patrimonio mediante los mismos
  componentes de forward; no fabrica caminos intrabar desde OHLC.
- Metadata inmutable de instrumentos y manifests con configuracion, datos,
  fuentes, commit y costes. Hashes verifican integridad, no origen autentico.
- Walk-forward con ventanas test disjuntas, calentamiento y purga; sin optimizar
  supuestos de costes para mejorar el resultado.
- Auditoria JSON valida, redaccion tipada, idempotencia y metricas de drawdown
  porcentuales verificadas. UNKNOWN no se sustituye por cero.
- Bloqueo de capacidad broker en esta release: cambiar flags, presentar una
  aprobacion en metadata o llamar directamente al adapter no habilita ordenes.

Contratos y compatibilidad estan en `PROJECT_SPEC.md`, seccion 17. ADRs en
`docs/decisions/2026-10-05-*.md` documentan cambios y sus limites.

## Evidencia y limites

Las pruebas automatizadas usan clientes falsos y fixtures sinteticas; no se han
enviado ordenes ni abierto una cuenta real. El replay integrado comprueba
apertura/cierre paper, evolucion del patrimonio, datos futuros/faltantes,
auditoria fallida, limites con exposicion, medianoche UTC y determinismo.

El diagnostico anterior a la ultima correccion de tick grid reactivo las senales
pero produjo resultados netos negativos tras costes en EURUSD, GBPUSD y USDJPY.
Los datos inspeccionados de febrero-mayo de 2026 son desarrollo/diagnostico y
no pueden reutilizarse como holdout final. El reporte de candidatos independientes
declara `full_risk_pipeline_applied=False`; no representa el replay estatal.

La verificacion global de paridad sigue incompleta. El inventario del motor
legacy comparte 7/16 contratos de etapas y conserva nueve brechas. El nuevo
replay se etiqueta `STATEFUL_EXPLICIT_QUOTE_REPLAY`; no se usa para convertir
ese inventario parcial en una certificacion integral o de fills del broker.

La revision local encontro MetaTrader 5 y MetaEditor instalados, sin proceso de
terminal activo durante la comprobacion. Los archivos MQL5 actuales son
placeholders vacios: no hay un EA nativo compilado. El trabajo ejecutable y
probado descrito aqui corresponde a Python. No se inicio el terminal.

## Pendientes que impiden promocion

1. Capturas nuevas de quotes bid/ask y metadata del broker, con costes y moneda
   verificados. Los logs y CSV disponibles no aportan todos esos contratos.
2. Evidencia OOS intacta, muestra suficiente, baselines con costes comparables,
   walk-forward, Monte Carlo, sensibilidad y resultados por regimen/sesion.
3. Una estrategia con ventaja estadistica despues de costes. La correccion de
   software por si sola no la proporciona.
4. Forward paper representativo, modelo causal aprobado si se usa ML y revision
   especifica de ejecucion demo antes de crear una release que pueda operar.
5. Implementacion/compilacion/verificacion MQL5 si se entrega un EA nativo, tal
   como contempla la vision del proyecto. No se considera cumplida por Python.

Uso offline: `docs/testing/stateful-replay-input.md`. Fuentes publicas y decisiones
de metodologia: `docs/EXTERNAL_TRADING_BENCHMARK_2026-10-05.md`.
