# Replay offline con cotizaciones explicitas

Scope: `STATEFUL_EXPLICIT_QUOTE_REPLAY`. Conserva libro paper, riesgo y patrimonio
entre eventos y usa el mismo nucleo que forward. No conecta MT5 ni Telegram.
Un resultado de este replay no autoriza operaciones ni acredita rentabilidad.

Ejecutar desde el checkout revisado, con rutas absolutas:

```powershell
py -3.14 -B scripts/replay_stateful_quotes.py `
  --source-root '<checkout>' `
  --events '<captura>/events.jsonl' `
  --instrument-snapshot '<captura>/instruments.json' `
  --config '<config-investigacion>.ini' `
  --output-dir '<directorio-nuevo>' `
  --initial-balance 10000 --currency USD `
  --slippage-points 1 --commission-per-lot-round-turn 7 `
  --without-ml
```

Los importes y costes del ejemplo son ilustrativos; deben declararse segun la
fuente del experimento. `--without-ml` exige `PAPER_ALLOW_DISABLED_ML=True` en el
INI. Alternativamente, `--model-dir` identifica un bundle local de confianza
con fecha de disponibilidad causal; no descarga ni descubre modelos. Un modelo
ausente/invalido bloquea. Los defaults operativos no se modifican.

Cada linea contiene exactamente `event_id`, `timestamp_utc`, `quotes`,
`decisions`, `evidence`. No admite JSON duplicado, NaN, Infinity, timestamps sin
timezone, claves desconocidas ni strings donde se requieren numeros.

- `quotes`: mapa simbolo a todos los campos del contrato `MarketSnapshot`.
  Bid/ask son observaciones explicitas. Se requieren cotizaciones frescas para
  cada posicion abierta, con metadata igual al snapshot de instrumentos.
- `decisions`: array (puede estar vacio) de objetos `symbol`, `timeframe`,
  `bars`. Cada barra contiene `timestamp_utc` de apertura, `open`, `high`, `low`,
  `close`, `volume`, `spread_points`; `symbol` y `timeframe` opcionales deben
  coincidir con su contenedor. Incluir suficiente historia de calentamiento.
  No se aceptan aliases MT5 `tick_volume`/`spread` en este transporte.
- `evidence`: mapa simbolo a `observed_at_utc`, `broker_readiness_score`,
  `correlation` (null solo cuando no hay exposicion que requiera correlacion).
  El transporte preserva lo declarado; un numero no prueba la procedencia.
  Deben conservarse los registros de origen usados para calcularlo.

El motor conserva `inputs.jsonl`, snapshot de instrumentos, manifest, auditoria
SQLite/JSONL y `result.json` en un destino nuevo. Nunca altera la captura fuente.
No convierte maximos/minimos OHLC en ticks, no cierra posiciones artificialmente
al terminar datos y declara como desconocidas trayectorias no observadas.

Un libro overnight requiere una observacion completa exactamente a medianoche
UTC para su referencia diaria. Si falta, la simulacion se detiene: no reconstruye
ese patrimonio usando precios posteriores. Este requisito puede limitar la
utilidad de capturas de baja frecuencia; se debe resolver con datos adecuados.

Verificacion: `tests/python/test_stateful_replay_io.py` cubre transporte estricto
y ausencia de carga de modelos locales al deshabilitar ML explicitamente. Las
pruebas de motor y de revision independiente verifican transiciones de estado;
las fixtures sinteticas prueban software, no rentabilidad ni costes de broker.
