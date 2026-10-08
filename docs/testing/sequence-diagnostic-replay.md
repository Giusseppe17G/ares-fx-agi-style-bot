# Recalculo de secuencias preservadas

`scripts/replay_sequence_diagnostics.py` recalcula Monte Carlo y stress sobre
los trades ya preservados por `replay_backtest_correctness.py`. No vuelve a
seleccionar parametros, modificar fills ni consultar un broker. Cada simbolo
se analiza por separado: sumar esos resultados no produce un portfolio viable.

```powershell
py -3.14 -B scripts/replay_sequence_diagnostics.py --source-root . --diagnostic-dir docs/testing/evidence/2026-10-05-shared-pipeline/diagnostic-7abf90e --output-dir <directorio-nuevo> --seed 82 --iterations 2000
```

El directorio de salida debe ser nuevo. El script carga codigo del source-root
explicito, registra hashes del script, summary y CSV originales, y utiliza el
capital inicial del diagnostico. Verifica columnas y conteos; las funciones
cuantitativas validan valores y tiempos. Descarta de forma declarada columnas
de metadata/estrategia que esos calculos no consumen; no evalua el repr Python
que el exportador CSV antiguo guardaba en metadata. Conserva todos los campos
economicos originales y los inputs normalizados de cada reporte.

El scope es `PRESERVED_CANDIDATE_SEQUENCE_DIAGNOSTIC_NOT_PROMOTION`. Los manifests
identifican codigo, runtime, inputs y configuracion utilizados en el recalculo.
La referencia al hash original comprueba integridad, no autenticidad del broker.
Se heredan las limitaciones de costes ilustrativos, metadata supuesta y datos de
desarrollo inspeccionados. No se declara holdout ni aplicacion del riesgo de
portfolio. Nunca se habilita ejecucion.

El bootstrap IID usa PnL monetario fijo, sin lotaje adaptativo ni dependencia
serial. El campo compatible de probabilidad de ruina representa alcanzar un
drawdown del 30%, no insolvencia. La clasificacion legacy WATCHLIST no implica
PnL positivo ni aprobacion. Los escenarios operativos NOT_MODELED del stress
siguen pendientes; un resultado favorable tampoco acredita esos escenarios.

Verificacion inicial del script: smoke offline de 200 iteraciones por simbolo
sobre los 644 trades preservados, en un directorio temporal, completado sin
alterar entradas. Los tres diagnosticos de stress rechazaron esas secuencias.
La evidencia final debe registrar su propio commit y numero de iteraciones;
este smoke no sustituye ese reporte.
