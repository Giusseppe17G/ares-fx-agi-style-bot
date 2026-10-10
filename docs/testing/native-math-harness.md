# Verificacion matematica nativa aislada

Contrato: `PROJECT_SPEC.md` §17.11. ADRs:
`docs/decisions/2026-10-05-native-math-harness.md` y
`docs/decisions/2026-10-10-native-math-log-parser.md`.
Ambito: herramienta de pruebas y observabilidad. No cambia estrategia, riesgo,
ejecucion, EA ni fuentes Python de produccion. La release sigue sin capacidad
broker.

## Componentes

| Archivo | Funcion |
| --- | --- |
| `tests/mt5/NativeMathHarness.mq5` | EA de Tester que reutiliza las tres suites sin editarlas (31 + 1.103 + 1.348 = 2.482 aserciones). |
| `scripts/run_native_math_harness.ps1` | Staging nuevo en TEMP, compilacion, config `Model=3`, terminal portable oculto con timeout y limpieza por PID/ruta. |
| `scripts/check_native_math_logs.py` | Parser fail-closed de logs y config; escribe `native-math-log-evidence.json`. |
| `tests/python/test_native_math_harness.py` | Guards estaticos y pruebas del parser. No ejecuta MQL ni terminal. |

## Secuencia exacta aceptada

Un unico run limpio produce estos nueve registros, en este orden, con
`execution_authorized=false full_pipeline_verified=false` en cada registro
`AGI_NATIVE_MATH_*`:

1. `AGI_NATIVE_MATH_BEGIN version=native_math_harness_v1 expected_checks=2482 model_required=3 model_verified_in_mql=false`
2. `NATIVE_POLICY_HARNESS checks=31 failures=0`
3. `AGI_NATIVE_MATH_STAGE name=observer checks=31 failures=0 expected_checks=31 accepted=1`
4. `NATIVE_CLOSED_BAR_HARNESS checks=1103 failures=0`
5. `AGI_NATIVE_MATH_STAGE name=closed_bars ... accepted=1`
6. `NATIVE_CORE_INDICATORS_HARNESS checks=1348 failures=0`
7. `AGI_NATIVE_MATH_STAGE name=core_indicators ... accepted=1`
8. `AGI_NATIVE_MATH_TOTAL checks=2482 failures=0 ticks=0 accepted=1 wrapper_failures=0 stages=3 expected_checks=2482`
9. `AGI_NATIVE_MATH_COMPLETE ... accepted=1 reason=<entero> completed=1 ...`

El `reason` de `OnDeinit` se registra pero no prueba exito. Cualquier otra forma
falla con un motivo concreto:

| Motivo | Causa |
| --- | --- |
| `STAGE_MISSING` | El staging no existe o es un enlace. |
| `TESTER_CONFIG_INVALID` | Config ausente, no matematica, con agentes remotos/cloud, trading/DLL o entradas de cuenta. |
| `LOG_SOURCE_LINK`, `LOG_DIRECTORY_UNREADABLE`, `LOG_UNREADABLE`, `TOO_MANY_LOG_FILES`, `LOG_TOO_LARGE`, `LOG_DECODE_ERROR` | Fuente de log enlazada, oculta, ilegible, excesiva o no decodificable. |
| `MALFORMED_RECORD` | Gramatica, orden de campos, literal, flag o entero invalido; tipo desconocido; linea truncada. |
| `NATIVE_MATH_RECORDS_MISSING` | Ningun log (excepto el de compilacion) contiene registros. |
| `LOG_SOURCES_INCONSISTENT` | Dos directorios con registros distintos (espejo parcial o de otro run). |
| `WRAPPER_REJECTED` | Contexto no Tester, tick inesperado o ciclo de vida invalido. |
| `ASSERTION_FAILURES` | Alguna `ASSERTION_FAILED:`; se conservan hasta 100 etiquetas. |
| `COMPLETION_RECORD_MISSING` | Sin `AGI_NATIVE_MATH_COMPLETE` (abort, timeout o log truncado). |
| `RECORD_SEQUENCE_MISMATCH` | Duplicados, faltantes, orden distinto o cualquier conteo/flag distinto; incluye primer desajuste. |

## Fuentes de log

El parser no presupone la ruta exacta de los logs del agente local o del
journal del Tester. Considera todos los `.log` del staging salvo
`MQL5/Experts/NativeMathHarness/NativeMathHarness.log` (compilacion), agrupados
por directorio y leidos por nombre (rotacion diaria). Todo directorio con
registros debe contener exactamente la misma secuencia. Acepta UTF-16LE con BOM
(formato observado en los logs de MetaEditor preservados), BOM UTF-16BE/UTF-8,
UTF-16LE sin BOM y UTF-8 estricto. La evidencia guarda rutas relativas al
staging, bytes y SHA256 de cada archivo leido, nunca rutas absolutas del host.

## Ejecucion

```powershell
py -3.14 -B -m pytest tests/python/test_native_math_harness.py
# Solo con autorizacion separada para iniciar el terminal en Windows:
./scripts/run_native_math_harness.ps1
```

El runner exige compilacion `Result: 0 errors, 0 warnings,` anclada al inicio de
linea, binarios publicos y config sin cambios despues del run, salida del
terminal con codigo 0, limpieza verificada, parser con codigo 0 y
`passed=true` en la evidencia. Si el terminal no arranca sin cuenta, el estado
queda `NOT_VERIFIED`; no se introduce una cuenta para forzar la prueba.

## Verificacion de esta entrega (2026-10-10)

- 80 pruebas nuevas pasan con Python 3.14.4, pandas 3.0.2 y NumPy 2.4.4. Suite
  completa y fallos ajenos (reloj de fin de semana, un test intermitente previo)
  en `docs/testing/evidence/2026-10-10-native-math-parser/`.
- Mutaciones temporales detectadas por los guards y revertidas: orden de campos
  en el wrapper, `#undef` faltante, constante de conteo alterada, regex de
  compilacion sin anclar, `UseCloud=1` en el runner y conteo distinto en el parser.
- La cabecera del wrapper registra hashes de las suites; el de
  `ClosedBarWindowHarness.mq5` corresponde a sus bytes CRLF y los otros cuatro a
  LF. El test acepta ambas formas; el runner hashea los bytes reales del staging.

No se compilo el wrapper ni se inicio MetaTrader: el entorno de esta entrega es
Linux sin MetaEditor/terminal. Siguen pendientes, para una ejecucion Windows
autorizada: compilacion del wrapper combinado, ubicacion real de los logs,
replica completa del journal, arranque portable sin cuenta/simbolo en modo
matematico y codigo de salida del terminal. Un pase futuro solo verificaria
estas fixtures sinteticas en una build MQL concreta; no acredita broker, reloj
real, asignacion fallida, rentabilidad, ejecucion ni Strategy Promotion Gate.
