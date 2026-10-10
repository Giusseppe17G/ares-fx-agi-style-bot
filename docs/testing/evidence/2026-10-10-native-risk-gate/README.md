# Evidencia: risk gate nativo, emulacion C++ y endurecimiento (2026-10-10)

Arbol de trabajo sobre `573fed4` antes del commit que conserva este directorio.
Runtime: Linux, Python 3.14.4, pandas 3.0.2, NumPy 2.4.4, pytest 9.1.1,
g++ 13.3.0, PowerShell 7.4.6 (solo para parsear scripts). Rutas del host
sustituidas por `<repo>` y `<scratchpad>`. No hay MetaEditor ni terminal.

| Archivo | Contenido |
| --- | --- |
| `tests-real-clock-root.txt` | Suite completa con reloj real (sabado 2026-10-10 ~07:00 UTC): **2.785 passed, 0 fallos**. |
| `cpp-emulation.json` | Emulacion C++: barras 1.103/1.103, indicadores 1.348/1.348, risk gate 1.433/1.433; 0 warnings, sin informe UBSan. |
| `powershell-parse.txt` | Parser de PowerShell 7.4.6 sobre los 50 `scripts/*.ps1`: todos `OK`. |

Las corridas previas del mismo dia fallaban en 5 tests dependientes de la hora y
del etiquetado de fin de semana, y una vez en un test intermitente (ver
`../2026-10-10-native-math-parser/`). Con las correcciones de esta entrega la
suite pasa completa en una hora (02:00-07:00 UTC de sabado) que antes fallaba.

SHA256 de las fuentes principales en esta corrida:

- `src/mt5/Include/Risk/NativeRiskGate.mqh`: `e131b592b78fdf2c204cee2db19396d475ecff031b11ecf4be1410288f12ba9b`
- `src/mt5/Include/Contracts/RiskContract.mqh`: `ff6d0105d0469b478c4191ba47e7f7b1fee04b7756849d5d682c3785ca6f5f95`
- `tests/mt5/RiskGateHarness.mq5`: `40bff6c32fd007c251428a2331c5c9e440fd7664e17c335f67c2ed8f695f7b80`
- `tests/mt5/GeneratedRiskGateFixtures.mqh`: `4065d0133ad73a79b1e910b0709237a2488bdd9e619866eb84ad901b9ef3c2ac`
- `tests/fixtures/native_risk_gate_cases.json`: `0497918844b77ac8f6cb801dd9ce8346b25db2ad85b5bdfad47e02251fca57f3`
- `tests/mt5/NativeMathHarness.mq5`: `cafe9cac33508d40555420e4e74be77b12bbbbf863385fb3bf6d12278e50ebda`
- `scripts/check_native_math_logs.py`: `aebf742f3d62501848b58b39ae5e50a96d66fe1c94658c990926514a43acb555`
- `scripts/run_native_math_harness.ps1`: `5a009c96229ae8b3b764cae8ed368cdd71a63534bf1c6fcbf1c61e513c8ffb1c`
- `scripts/run_native_cpp_emulation.py`: `40fad87e8e6fca30a68d4dd62323329e5a222d9b5b5b424a8e5ac95c7b860ce3`
- `scripts/generate_native_risk_gate_fixtures.py`: `751991600666e85529e5b98bf4eb92f6bbfa60bd9ab297f1a209749441150022`

Mutaciones temporales (revertidas) detectadas por la emulacion: limite de
drawdown diario `>=` por `>`, producto exacto en lattice sustituido por producto
binario (falla el caso USDJPY con metadata), redondeo ingenuo del piso de lote,
eliminacion de las comprobaciones de rejilla de tick y de la auditoria. Tres de
ellas quedan automatizadas en `tests/python/test_native_cpp_emulation.py`.

Nada de esto ejecuta MQL5 en MetaTrader ni acredita rentabilidad, ejecucion
broker o el Strategy Promotion Gate.
