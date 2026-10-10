# Risk Gate nativo puro: fixtures diferenciales

Contrato: `PROJECT_SPEC.md` §17.12, paquete `native_risk_gate_v1`. ADR:
`docs/decisions/2026-10-10-native-risk-gate.md`. Ambito: riesgo nativo y
verificacion. No se conecta al EA, no construye ordenes y nunca autoriza
ejecucion. No cambia el motor Python de riesgo.

## API

```cpp
bool NativeEvaluateRisk(const NativeRiskLimits &limits, const NativeRiskAccount &account,
                        const MarketSnapshot &snapshot, const NativeRiskSignal &signal,
                        const NativeRiskPosition &positions[], const NativeRiskState &state,
                        NativeRiskDecision &decision);
```

Estructuras en `src/mt5/Include/Contracts/RiskContract.mqh`; implementacion en
`src/mt5/Include/Risk/NativeRiskGate.mqh`. Todas las entradas son explicitas,
incluido `now_utc_msc`. Un rechazo limpia lote, riesgo y porcentajes; el
`decision.version` es siempre `native_risk_gate_v1` y los flags
`execution_authorized`/`full_pipeline_verified` siempre son false.

## Fixtures

```bash
python -B scripts/generate_native_risk_gate_fixtures.py --check
python -B -m pytest tests/python/test_native_risk_gate_fixtures.py
python -B scripts/run_native_cpp_emulation.py --suite risk_gate
```

- 113 casos sinteticos: 95 comparables con el `RiskEngine` real de Python (94
  exactos en lattice, incluidos 12 de precedencia, y uno con tick value fuera
  del lattice) y 18 de politica nativa con su alcance declarado. 36 casos
  aceptan y verifican tambien el reinicio posterior del resultado.
- Cada caso guarda entradas completas con hash, la salida Python, la
  expectativa nativa y las tolerancias. Los comparables copian a Python sin
  ajustes; solo el caso con tick value fuera del lattice usa 4 ulps en importes
  y el lote sigue siendo exacto (el generador demuestra que no esta en un borde).
- 1.433 aserciones estaticas: 1.423 generadas y 10 manuales de aritmetica de
  lattice, cuyos literales se verifican con `Decimal` en Python.
- Todos los codigos de rechazo nativos estan cubiertos salvo
  `MAX_RISK_PER_TRADE`, inalcanzable tras el limite del propio dimensionado y
  conservado como guardia defensiva igual que en Python.

| Alcance | Casos | Significado |
| --- | ---: | --- |
| `COMPARABLE` | 94 | Igual a Python, exacto. |
| `COMPARABLE_NON_LATTICE_TICK_VALUE` | 1 | Igual a Python; importes con 4 ulps. |
| `NATIVE_LIMITS_CODE` | 6 | Python rechaza con `INTERNAL_ERROR`; nativo con `RISK_LIMITS_INVALID`. |
| `NATIVE_LIMITS_STRICTER` | 3 | Techos/limites positivos que la config Python no exige. |
| `NATIVE_STATE_STRICTER` | 1 | Conteo de perdidas negativo. |
| `NATIVE_GRID_STRICTER` | 3 | Precios fuera de la rejilla de tick o volumen fuera del lattice. |
| `NATIVE_NUMERIC_STRICTER` | 4 | NaN/Inf que Python deja pasar. |
| `NATIVE_CONTRACT` | 1 | Direccion invalida, no representable en Python. |

## Resultado de esta entrega (2026-10-10)

- 238 pruebas Python del modulo pasan (Python 3.14.4); el generador es
  determinista e independiente del interprete (`--check` tambien con 3.13).
- Emulacion C++ (§17.13): 1.433/1.433 aserciones ejecutadas sin fallos,
  sin warnings y sin informe UBSan. Mutaciones del limite de drawdown, del
  producto exacto en lattice, de la auditoria, de la rejilla de tick y del
  redondeo del lote fueron detectadas.
- **No se compilo con MetaEditor ni se ejecuto en MetaTrader.** Compilacion y
  run del Tester quedan pendientes de una ejecucion Windows autorizada
  (`compile_native_observer.ps1` y `run_native_math_harness.ps1`).

El gate no decide referencias diarias, perdidas consecutivas ni cooldowns: los
recibe del llamador. Una integracion futura en el EA debe derivarlos de estado
auditado. Un resultado positivo no acredita rentabilidad, ejecucion broker ni
el Strategy Promotion Gate.
