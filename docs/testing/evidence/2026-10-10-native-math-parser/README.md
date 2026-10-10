# Evidencia: parser de logs nativo matematico (2026-10-10)

Codigo verificado: commit `71c5336e4afd5cddd78d993b3922842a07684438`.
Hashes de las fuentes nuevas en el momento de ambas corridas:

- `scripts/check_native_math_logs.py`: `fd1f024c04c8ae44cf7174587a7ca49578b89d9d49c3fc2ff7376e1cd2302c55`
- `tests/python/test_native_math_harness.py`: `8f91cca7646ead29a3f20a8dbd083aa0a348d2c1c13f5aea6077d9dab6c8d3f6`

Runtime: Linux, Python 3.14.4, pandas 3.0.2, NumPy 2.4.4 y pytest 9.1.1 (el
mismo runtime de referencia que las fixtures nativas). Las rutas absolutas del
host se sustituyeron por `<repo>` y `<scratchpad>`; nada mas se edito.
No hay MetaEditor ni terminal MetaTrader en este entorno.

## Corridas de la suite completa

| Log | Reloj | Resultado |
| --- | --- | --- |
| `tests-real-clock-root.txt` | Real, sabado 2026-10-10 | 2.522 passed, 5 failed |
| `tests-weekday-clock-root.txt` | `weekday_clock.py`: miercoles 2026-10-07 12:00 UTC | 2.526 passed, 1 failed |

Los 80 tests de `test_native_math_harness.py` pasan en ambas corridas.

Los cinco fallos con reloj real (`test_mt5_data_mode.py` x3 y
`test_phase28_mt5_time_normalization.py` x2) dependen del reloj de pared: en fin
de semana el pipeline devuelve `MARKET_CLOSED_OR_NO_TICKS`. Pasan con el reloj
fijado en dia laborable. Ya fallaban antes de este cambio en la misma fecha.

El fallo de la corrida laborable,
`test_forward_replay_lifecycle.py::test_shared_audit_failures_match_actual_callers[PAPER_CYCLE_COMPLETED]`,
es intermitente y previo: el test identifica loggers por `id(logger)` y CPython
puede reutilizar ese id cuando el primer logger ya fue recolectado, dejando
`len(failures) == 1`. Paso 3/3 al repetirlo con el mismo plugin y 2/2 el modulo
completo con reloj real. No se modifico en esta entrega porque esta fuera de su
alcance.

`weekday_clock.py` es un plugin de diagnostico que usa `time-machine` 3.5.1. No
es dependencia del proyecto ni se usa en `pyproject.toml`. Reproduccion:

```bash
PYTHONPATH=docs/testing/evidence/2026-10-10-native-math-parser \
  python -B -m pytest -p no:cacheprovider -p weekday_clock -rf
```

Estas corridas no ejecutan MQL ni acreditan compilacion, runtime del Tester,
rentabilidad, ejecucion broker ni el Strategy Promotion Gate.
