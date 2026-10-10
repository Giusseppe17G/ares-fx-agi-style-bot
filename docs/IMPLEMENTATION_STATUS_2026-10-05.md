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
- Ciclo economico unico para el `.run` real del forward y replay: cuenta/conexion
  por ciclo, cotizaciones completas antes de gestionar el libro, evidencia broker
  fechada y estado de riesgo actualizado entre candidatos. Auditoria incompleta
  deja bloqueo durable que se conserva al reiniciar, incluso si falla el propio
  evento de bloqueo. Pausas manuales no se convierten en pausas autoexpirables.
- Stops dinamicos conservadores sobre tick_size y spread decimal compartido.
  Timestamps Python futuros no se convierten en frescos mediante offset inferido.
- Metadata inmutable de instrumentos y manifests con configuracion, datos,
  fuentes, commit y costes. Hashes verifican integridad, no origen autentico.
- Walk-forward con ventanas test disjuntas, calentamiento y purga; sin optimizar
  supuestos de costes para mejorar el resultado.
- Comparacion offline predeclarada de trend pullback: cinco parametros realmente
  aplicados, umbrales 62/70/78 sin seleccion, periodos comunes 60/20/20 con
  metricas propias, warmup 250 y exclusion previa de horizonte incompleto.
  Plan persistido antes de evaluar, hashes verificados antes/despues de cada
  celda y bloqueo ante cambios. Moneda, instrumento, lotaje y costes explicitos;
  codigo no convierte datos de desarrollo en holdout ni autoriza promocion.
- Motor OHLC 0.3.2 transmite tick_size real al fill y valida la rejilla de SL/TP.
  BE/trailing usan distancias decimales y stops conservadores; las regresiones
  reproducen precios antes inejecutables y activacion perdida de BE exacto.
- Monte Carlo conserva la secuencia realmente mezclada y separa su indice
  sintetico del calendario. Stress declara aproximaciones posteriores al trade;
  retrasos, sesiones, fill rate y barras ausentes siguen NOT_MODELED. Reportes v2
  guardan entradas normalizadas, configuracion, runtime y hashes reproducibles.
- Auditoria JSON valida, redaccion tipada, idempotencia y metricas de drawdown
  porcentuales verificadas. UNKNOWN no se sustituye por cero.
- Bloqueo de capacidad broker en esta release: cambiar flags, presentar una
  aprobacion en metadata o llamar directamente al adapter no habilita ordenes.
- Base nativa MQL5 de observacion: cuenta demo verificada cada ciclo, validacion
  de cotizaciones/metadata/reloj, auditoria local obligatoria y gate de ejecucion
  siempre bloqueado. No implementa aun estrategia ni riesgo nativos.
- Selector nativo puro de barras cerradas, aislado del EA: timestamps UTC
  explicitos, limites de calendario/reloj, validacion de todo el lote y limpieza
  del resultado ante fallo. Conserva gaps y excluye barras abiertas/futuras;
  no adquiere datos ni calcula indicadores. Fixtures distinguen coincidencias
  con Python de comprobaciones nativas deliberadamente mas estrictas.
- Paquete nativo puro de EMA20/50/200, RSI14 y ATR14: revalida la ventana en cada
  llamada y conserva las semillas Python y todo el prefijo recibido. Exige 200
  barras para publicar el conjunto; limpia resultados ante fallo y no se conecta
  al EA. El warmup 250 de investigacion sigue siendo una politica distinta.
- VWAP Python rechaza productos/sumas no representables y conversiones de tipos
  no normalizados; el fallback al precio tipico corresponde solo a volumen
  acumulado cero. No convierte overflow en una cotizacion aparentemente valida.

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

La ampliacion `496140ec26923c48ec9e5f9a485e87bf89e773bc` de lifecycle,
precision, reloj UTC y evidencia sintetica pasa
**2.101 tests Python** en 97,89 segundos. Log:
`docs/testing/evidence/2026-10-05-shared-pipeline/tests-lifecycle-root-final.txt`.
La primera integracion detecto un consumidor de stress que no admitia resultados
NOT_MODELED; se corrigio y se conserva el log fallido anterior. `git diff --check`
pasa. Los tests siguen aislados de MT5 real y del directorio original de datos.

La ampliacion `3e9b4d4a7bd2e7d57684669892a68570def676ca` del estudio
predeclarado y motor OHLC 0.3.2 pasa
**2.213 tests Python** en 179,65 segundos. Log:
`docs/testing/evidence/2026-10-05-shared-pipeline/tests-predeclared-root.txt`.
Las dos advertencias NumPy pertenecen al test que provoca un desbordamiento
monetario y verifica su rechazo; no corresponden a una investigacion de mercado.
La corrida completa se hizo con fuentes congeladas e incluye CLI desde otra
CWD, persistencia, hashes, parametros efectivos, causalidad, moneda y geometria.
El checkout original permanece limpio. No se ejecutaron ordenes ni terminal.

El modulo nativo `37113e0d63855422d57e3c97d1819601c674be57` pasa la suite
completa: **2.323 tests Python**, dos advertencias del desbordamiento intencional,
en 180,41 segundos. Log: `docs/testing/evidence/2026-10-05-shared-pipeline/tests-native-closed-bars-root.txt`.
La integracion `101b48c9cb0ff0e4fe2eb479e8b2157f7f61165f` conserva las fixtures
canonicas byte a byte (`--check`) y vuelve a pasar sus 108 tests especificos.

El estudio predeclarado de ese commit limpio completo sus 27 celdas:
tres umbrales, tres simbolos y tres tramos temporales. Las nueve celdas train y
las nueve validation tienen PnL negativo. En development_test solo EURUSD/78
(+26,60 USD supuestos, PF 1,0074) y GBPUSD/78 (+56,20, PF 1,0188) son positivos;
sus tramos anteriores siguen negativos. **25/27 resultados negativos** y
ningun PF supera 1,15. No se elige una configuracion ni se cambia el protocolo
para eliminar esos resultados.

La auditoria independiente verifica las 27 identidades, todos los hashes y
metricas recalculadas. Son 69.000 registros de candidatos de una estrategia
individual, con solapamiento temporal, no una cartera ni observaciones
estadisticamente independientes. Costes y valor del tick siguen siendo
ilustrativos; desarrollo ya inspeccionado no es OOS final. Evidencia completa,
datos originales/canonicos y bytes de codigo preservados en
`docs/testing/evidence/2026-10-05-shared-pipeline/predeclared-3e9b4d4/`.

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

El recalculo de secuencias con codigo limpio `496140e`, seed 82 y 2.000
bootstraps por simbolo produjo los siguientes diagnosticos. Se ejecutaron desde
otro directorio, verificando commit, hashes de fuentes y CSV preservados:

| Simbolo | Probabilidad simulada de DD >= 30% | Retorno percentil 5 | Stress |
| --- | ---: | ---: | --- |
| EURUSD | 9,25% | -30,01% | REJECTED |
| GBPUSD | 77,25% | -62,68% | REJECTED |
| USDJPY | 43,15% | -45,75% | REJECTED |

Son secuencias IID de PnL monetario fijo, con capital ilustrativo 10.000 y sin
redimensionar lotes, no probabilidades predictivas del bot con riesgo de portfolio.
DD del 30% no significa insolvencia. Los costes/metadatos originales siguen
siendo supuestos; no se alteraron fills. La clasificacion legacy Monte Carlo
WATCHLIST de EURUSD tampoco implica beneficio ni promocion. Los escenarios
operativos de stress siguen NOT_MODELED. Evidencia:
`docs/testing/evidence/2026-10-05-shared-pipeline/sequence-496140e/`.

La verificacion global de paridad sigue incompleta. El inventario del motor
legacy comparte 7/16 contratos de etapas y conserva nueve brechas. El nuevo
replay se etiqueta `STATEFUL_EXPLICIT_QUOTE_REPLAY`; no se usa para convertir
ese inventario parcial en una certificacion integral o de fills del broker.

La ampliacion del lifecycle verifica episodios controlados a traves de
`ForwardShadowBot.run`, adquisicion con cliente falso, features/estrategia/riesgo
reales, ledger SQLite, gestion y replay con los mismos inputs. Compara trazas,
trades, equity, riesgo, pausas y rechazos en gaps de stop, TP, BE/trailing,
reintento de vela, evidencia caducada y quotes ausentes. La evidencia positiva
de esos episodios corresponde al perfil ACTIVE; los tests de gates micro/stable
no certifican por si solos paridad economica completa de cada perfil. Se
conserva `full_pipeline_verified=False`. Ver
`docs/testing/forward-replay-lifecycle.md`.

La revision local encontro MetaTrader 5 y MetaEditor instalados. La compilacion
integrada con MetaEditor 5.0.0.5833 produjo **0 errores y 0 advertencias** en el
EA observador, ObservationPolicyHarness y ClosedBarWindowHarness. Se verificaron
los 17 hashes de fuentes, script, tres logs y tres binarios contra el staging
aislado; evidencia en `docs/testing/evidence/native-closed-bars-integrated-2026-10-05/`.
Git puede cambiar bytes de fin de linea, por lo que se conserva tambien la
compilacion anterior y su manifest sin atribuirle los bytes del nuevo checkout.
No se inicio el terminal ni se instalaron binarios. Las 31 aserciones anteriores
y las 1.103 llamadas de asercion del nuevo harness **no se ejecutaron**.
Tests Python y compilacion no acreditan comportamiento runtime MQL5, asignacion
fallida, autenticidad UTC ni paridad integral. Estrategia/riesgo nativos pendientes.

La ampliacion de indicadores se compilo despues en cuatro objetivos (los tres
anteriores y CoreIndicatorsHarness), con cero errores y advertencias. Root
verifico 21 fuentes, script, cuatro logs y cuatro binarios por hash. Evidencia:
`docs/testing/evidence/native-core-indicators-2026-10-05/`. Las 49 fixtures
sinteticas tienen 98 pruebas Python y 1.348 llamadas de asercion MQL compiladas,
todavia no ejecutadas. Las tolerancias de regresion no son una cota universal de
error ni modifican umbrales de estrategia. El RSI cuyo cociente desborda se
rechaza explicitamente aunque pandas termine saturando a 100.

La regresion de VWAP verifica tambien el `.run` real de forward con cliente
falso y replay: ninguno produce decisiones ni trades con volumen que desborda.
Forward registra fallo de features y excluye la candidatura durante adquisicion;
replay detiene su lifecycle. Son modos de recuperacion distintos, no evidencia
de paridad integral para ese fallo. La auditoria se conserva en ambos.

Suite completa de esta ampliacion: **2.447 tests Python pasan** en 190,11
segundos, con las mismas dos advertencias del desbordamiento monetario
intencional. Log: `docs/testing/evidence/2026-10-05-shared-pipeline/tests-core-indicators-vwap-root.txt`.
Ambos generadores de fixtures pasaron `--check` antes de esa corrida. No se
repitio el estudio financiero para atribuir beneficio a cambios de software.

La ampliacion del 2026-10-10 completa la herramienta de verificacion matematica
nativa (§17.11): el runner invocaba `scripts/check_native_math_logs.py`, que no
existia, y fallaba antes de iniciar nada. El parser nuevo es fail-closed: solo
acepta la secuencia exacta de nueve registros con 2.482 aserciones, sin
rechazos, ticks ni fallos, y una config `Model=3` sin cuenta ni agentes
remotos. El runner ancla la comprobacion de compilacion (la subcadena anterior
aceptaba `10 errors, 0 warnings`) y ejecuta el parser con `-I`. 80 pruebas nuevas
cruzan gramatica, conteos, macros, include guards y runner; mutaciones
temporales confirmaron que detectan regresiones. Ver
`docs/testing/native-math-harness.md` y
`docs/decisions/2026-10-10-native-math-log-parser.md`. **No se compilo el
wrapper ni se inicio MetaTrader** (entorno Linux); el runtime MQL sigue sin
verificar. Suite completa con Python 3.14.4/pandas 3.0.2/NumPy 2.4.4 en sabado:
**2.522 passed y 5 fallos** que dependen del reloj (mercado cerrado). Con el
reloj fijado en dia laborable pasan, y solo falla de forma intermitente un test
previo que identifica loggers con `id()`. Logs:
`docs/testing/evidence/2026-10-10-native-math-parser/`.

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
   El wrapper matematico ya tiene runner, parser y guards Python; su
   compilacion combinada y el run del terminal siguen pendientes de una
   ejecucion Windows autorizada.
6. Completar la validacion financiera del nuevo estudio predeclarado, incluidos
   baselines y datos intactos. Las etiquetas de candidatos del runner legacy
   no aplican parametros distintos al backtest y el
   assessment reutiliza la misma muestra como train/test. Ahora lo declara
   `OOS_NOT_EVALUATED`, limita resultados a diagnostico y no aprueba candidatos.
   El runner nuevo aplica parametros y separa tramos, pero sus resultados de
   desarrollo tampoco permiten seleccionar una estrategia validada.

Uso offline: `docs/testing/stateful-replay-input.md`. Fuentes publicas y decisiones
de metodologia: `docs/EXTERNAL_TRADING_BENCHMARK_2026-10-05.md`.
Proximo paquete de evidencia: `docs/testing/next-evidence-protocol.md`.
Compilacion y limitaciones nativas: `docs/testing/native-observation.md`.
Verificacion matematica nativa: `docs/testing/native-math-harness.md`.
Recalculo de secuencias: `docs/testing/sequence-diagnostic-replay.md`.
