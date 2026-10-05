# Validacion del snapshot de instrumentos

Modulo: metadata de instrumentos y procedencia para investigacion/backtesting.
No modifica estrategia ni habilita ejecucion demo/real.

## Contrato de captura

```python
from agi_style_forex_bot_mt5.instrument_registry_builder import build_instrument_registry_snapshot

snapshot = build_instrument_registry_snapshot(
    client=read_only_client,
    symbols={"EURUSD": "EURUSD.raw"},
    captured_at_utc=aware_capture_datetime,
)
snapshot.write(output_directory / "instruments.json")
```

El cliente se inyecta y solo se invoca `symbol_info(broker_symbol)`. El modulo no
importa MetaTrader5 ni llama inicializacion, login, seleccion de simbolos,
account_info, order_check, order_send o shutdown. El llamador es responsable de
su conexion previamente establecida. No se consulto una terminal durante las
pruebas; toda captura usa dobles de prueba.

El mapa canonical/broker es explicito. Se valida antes de consultar el cliente;
no se descubren sufijos. El nombre devuelto debe coincidir exactamente con el
broker_symbol solicitado. El par canonico usa seis letras y debe coincidir con
currency_base + currency_profit. Los nombres del broker admiten letras, numeros,
`_ . # + / -`, con un maximo de 64 caracteres; otros formatos requieren revision
explicita, sin reemplazar caracteres ni adivinar aliases.

Campos conservados: symbol, canonical_symbol, broker_symbol, digits, point,
tick_size, tick_value, contract_size, min_volume, max_volume, volume_step,
stops_level_points, freeze_level_points, currency_base, currency_quote, source y
currency_margin. `min_volume/max_volume` corresponden a `volume_min/volume_max`
MT5; `currency_quote` conserva el nombre existente para `currency_profit`.
`currency_margin` se guarda si esta disponible, y vale null si falta. Ningun
campo requerido se sustituye por un valor supuesto. Otros campos del cliente
(incluidos servidor, cuenta, rutas y credenciales) no se copian ni se hashean.

Se rechazan valores ausentes, bools donde se requieren numeros, cadenas
numericas, numeros no finitos o no positivos, enteros fraccionarios, min_volume
mayor que max_volume, pasos mayores al volumen maximo, point incompatible con
digits, y tick_size que no es multiplo entero de point. Cero es valido para
stops/freeze. Una sola entrada invalida impide devolver el snapshot completo.
Los errores del cliente se reemplazan por errores estructurados sin incluir
mensajes sensibles ni su traceback encadenado.

## Formato y hashes

El JSON contiene exactamente:

- `schema_version`: `1.0`.
- `source`: `mt5:symbol_info`.
- `captured_at_utc`: fecha ISO-8601 con offset UTC explicito.
- `instrument_count`, `symbols` ordenados e `instruments` por simbolo canonico.
- `metadata_hash`: SHA256 del objeto `instruments` normalizado.
- `snapshot_hash`: SHA256 del resto del documento, incluido metadata_hash y fecha.

La serializacion de hash ordena claves, usa separadores `,`/`:`, ASCII escapado,
UTF-8 y rechaza NaN/Infinity. El hash de metadata cambia ante cambios de campos,
alias o fuente, y permanece igual ante distinta fecha/ruta/orden de captura.
El hash del snapshot incluye fecha. Los hashes verifican integridad y
reproducibilidad; no son firmas ni prueban autenticidad del origen.

`InstrumentRegistrySnapshot.read(path)` valida esquema, tipos, campos exactos y
ambos hashes. `InstrumentRegistry.from_dataset(data_dir)` reconoce el mismo
formato y ejecuta esa verificacion. Una version desconocida, campos faltantes,
claves JSON duplicadas, cambios de metadata o hashes incorrectos fallan cerrados.
Los sidecars legacy siguen siendo legibles, pero no pasan como snapshots
verificados. No hay migracion silenciosa ni degradacion a valores supuestos.

La escritura exige directorio padre existente y destino nuevo. Se escriben y
sincronizan los bytes en un temporal del mismo directorio; un hardlink publica
el archivo completo sin reemplazar un destino existente. Un filesystem que no
permite hardlinks produce error, sin fallback a sobrescritura. El registro y las
specs son inmutables; una copia devuelta por as_dict no puede cambiar los hashes.

## Reproducibilidad y limites

Un llamador que usa RunManifest debe incorporar este sidecar entre dataset_paths
y registrar metadata_hash/snapshot_hash en el reporte. Sin ese enlace, cambiar
las condiciones del instrumento puede no cambiar la identidad de la corrida.
El hook RunManifest/CLI pertenece al agente integrador, no a este modulo.

El snapshot conserva propiedades observadas en el instante declarado; no prueba
que fueran las mismas durante un dataset historico. El timestamp se inyecta y
su exactitud depende del llamador. No certifica frescura de ticks, tipo de cuenta,
costos, conversiones historicas, permission de trading ni validez de una
estrategia. `trade_tick_value` conserva la semantica MT5 observada: no se infiere
moneda de cuenta a partir de currency_profit/currency_margin. La disponibilidad
de metadata no basta para aprobar sizing, riesgo o Strategy Promotion Gate.

Referencias oficiales consultadas el 2026-10-05:
[symbol_info](https://www.mql5.com/en/docs/python_metatrader5/mt5symbolinfo_py) y
[propiedades de simbolos](https://www.mql5.com/en/docs/constants/environment_state/marketinfoconstants).
La primera documenta el resultado namedtuple/None; la segunda define los campos
de precision, volumen, restricciones y monedas usados aqui.

## Pruebas

```powershell
py -3.14 -B -m pytest tests/python/test_instrument_registry_builder.py tests/python/test_phase82_backtest_live_parity.py
```

Casos automatizados: captura con mapping y objeto, cliente limitado a lectura,
ausencia de campos requeridos, tipos/limites invalidos, aliases ambiguos,
campos sensibles descartados, errores redactados, reproducibilidad, roundtrip,
integridad alterada, esquema parcial, JSON duplicado, inmutabilidad y escritura
exclusiva/fallida sin archivo parcial. Las fixtures de pytest aislan todas las
escrituras en temporales; no se escriben datos productivos ni se ejecuta MT5.

Pendiente externo: capturar metadata real mediante un cliente ya conectado y
autorizado, vincularla al dataset correcto y verificar las conversiones de riesgo
para el periodo bajo estudio. No se presenta ninguna captura sintetica como
evidencia real de broker.
