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
- Base nativa MQL5 de observacion: cuenta demo verificada cada ciclo, validacion
  de cotizaciones/metadata/reloj, auditoria local obligatoria y gate de ejecucion
  siempre bloqueado. No implementa aun estrategia ni riesgo nativos.

Contratos y compatibilidad estan en `PROJECT_SPEC.md`, seccion 17. ADRs en
`docs/decisions/2026-10-05-*.md` documentan cambios y sus limites.

## Evidencia y limites

Las pruebas automatizadas usan clientes falsos y fixtures sinteticas; no se han
enviado ordenes ni abierto una cuenta real. El replay integrado comprueba
apertura/cierre paper, evolucion del patrimonio, datos futuros/faltantes,
auditoria fallida, limites con exposicion, medianoche UTC y determinismo.

Validacion del codigo guardado en `9aba3529306da2fc31948850807f5c54ec542dec`:
**1.763 tests pasan** desde la raiz y **1.763 pasan** desde un directorio externo,
con Python 3.14. Logs en `docs/testing/evidence/2026-10-05-shared-pipeline/`.
`git diff --check` pasa. El checkout original se conserva sin modificaciones.

La ampliacion posterior, guardada en `7abf90e4cc1cc35c9c66ce8d7f215cf7145ae1d3`
(motor 0.3.1, reporte observacional 2.0 y observador nativo), pasa
**1.940 tests Python** desde la raiz en 71,20 segundos. Log:
`docs/testing/evidence/2026-10-05-shared-pipeline/tests-final-root-1940.txt`.
Los tests no acreditan una ventaja financiera ni ejecucion nativa en terminal.

El diagnostico del commit `7abf90e` (motor 0.3.1, con tick grid y metricas
corregidas), ejecutado desde un directorio externo, produjo:

| Simbolo | Trades | Profit factor | PnL neto simulado |
| --- | ---: | ---: | ---: |
| EURUSD | 173 | 0.866 | -970 |
| GBPUSD | 256 | 0.721 | -3.625 |
| USDJPY | 215 | 0.806 | -2.095 |

Son 644 candidatos independientes con lotaje fijo ilustrativo. El PnL esta
expresado en las unidades de cuenta supuestas; no representa dinero operado,
lotaje aprobado por portfolio ni rentabilidad OOS. Los tres resultados son
negativos incluso bajo los supuestos de costes declarados. La correccion
metrica 0.3.1 incluye primer periodo/capital inicial y recovery monetario.
Los tres archivos de trades son identicos byte a byte al diagnostico `9aba352`;
la correccion no modifica fills ni PnL. Se verificaron hashes de codigo, script
y los tres datasets. Ambos reportes estan preservados en
`docs/testing/evidence/2026-10-05-shared-pipeline/`.

El spread original es cero en 18.845/20.000 barras EURUSD (94,225%),
8/20.000 GBPUSD (0,04%) y 17.228/20.000 USDJPY (86,14%). No se puede afirmar que
esos valores representen los costes reales del broker. Se conservan tal cual y
se declara su procedencia no verificada; no se imputan costes para buscar un
resultado favorable.

Los datos inspeccionados de febrero-mayo de 2026 son desarrollo/diagnostico y
no pueden reutilizarse como holdout final. El reporte de candidatos independientes
declara `full_risk_pipeline_applied=False`; no representa el replay estatal.

La verificacion global de paridad sigue incompleta. El inventario del motor
legacy comparte 7/16 contratos de etapas y conserva nueve brechas. El nuevo
replay se etiqueta `STATEFUL_EXPLICIT_QUOTE_REPLAY`; no se usa para convertir
ese inventario parcial en una certificacion integral o de fills del broker.

La revision local encontro MetaTrader 5 y MetaEditor instalados. Se sustituyo
el EA vacio por una base de observacion y se compilaron EA y harness con
MetaEditor 5.0.0.5833: **0 errores y 0 advertencias** en ambos. Los hashes del
manifest coinciden con las fuentes actuales. Los otros contratos nativos no
implementados siguen pendientes; el trabajo de estrategia/riesgo probado es
Python. No se inicio el terminal ni se instalaron binarios. Las 31 aserciones
del harness MQL5 se compilaron pero no se ejecutaron; 20 guardianes de fuente
Python verifican restricciones estaticas, no comportamiento runtime.

## Pendientes que impiden promocion

1. Capturas nuevas de quotes bid/ask y metadata del broker, con costes y moneda
   verificados. Los logs y CSV disponibles no aportan todos esos contratos.
2. Evidencia OOS intacta, muestra suficiente, baselines con costes comparables,
   walk-forward, Monte Carlo, sensibilidad y resultados por regimen/sesion.
3. Una estrategia con ventaja estadistica despues de costes. La correccion de
   software por si sola no la proporciona.
4. Forward paper representativo, modelo causal aprobado si se usa ML y revision
   especifica de ejecucion demo antes de crear una release que pueda operar.
5. Verificacion runtime del observador y posterior implementacion/verificacion
   de estrategia/riesgo nativos si se entrega el EA completo contemplado en la
   vision. Compilar el observador no acredita esos modulos ni paridad Python.

Uso offline: `docs/testing/stateful-replay-input.md`. Fuentes publicas y decisiones
de metodologia: `docs/EXTERNAL_TRADING_BENCHMARK_2026-10-05.md`.
Proximo paquete de evidencia: `docs/testing/next-evidence-protocol.md`.
Compilacion y limitaciones nativas: `docs/testing/native-observation.md`.
