# PROJECT_SPEC.md

## 1. Vision

`AGI_STYLE_FOREX_BOT_MT5` sera un Expert Advisor modular para MetaTrader 5 orientado a Forex, con soporte para investigacion, backtesting, gestion de riesgo estricta, auditoria de decisiones y notificaciones operativas.

El proyecto se inspira en caracteristicas publicamente observables de EAs Forex de alto rendimiento: disciplina de riesgo, filtrado de mercado, ejecucion robusta, monitoreo y mejora iterativa. No copia codigo propietario, no replica marcas privadas y no afirma ser un producto original de terceros.

## 2. Principios

- Seguridad primero: si algo no esta validado, no se opera.
- `DEMO_ONLY=True` por defecto.
- Todo trade debe tener SL y TP antes de enviarse.
- Toda senal debe quedar auditada, incluso si es rechazada.
- El bot debe poder explicar por que acepto o rechazo una operacion.
- La estrategia, el riesgo, la ejecucion, el logging y el backtesting deben estar desacoplados.
- Los contratos entre modulos son mas importantes que las implementaciones internas.

## 3. Alcance Inicial

Incluido:

- Estructura base para EA MT5 en MQL5.
- Contratos de senales, riesgo, ejecucion, eventos y backtesting.
- Configuracion segura por defecto.
- Especificacion de modulos.
- Preparacion para trabajo multiagente.

No incluido todavia:

- Implementacion completa de estrategia.
- Conexion real a Telegram.
- Persistencia real en base de datos.
- Motor completo de backtesting.
- Optimizacion de parametros.
- Operacion en vivo.
- Operacion en cuenta real, incluso si se cambia manualmente `DEMO_ONLY`.

## 4. Arquitectura General

```text
Market Data
  -> Strategy Engine
  -> Signal Contract
  -> Risk Gate
  -> Execution Gate
  -> MT5 Order Executor
  -> Position Monitor
  -> Logging/Database
  -> Telegram Notifications
```

Ningun modulo puede saltarse el `Risk Gate` ni el `Execution Gate`.

## 5. Modulos

### 5.1 Strategy Engine

Responsabilidad:

- Leer datos de mercado normalizados.
- Calcular condiciones de entrada/salida.
- Emitir una senal candidata.
- No decidir lotaje final.
- No ejecutar ordenes.

Entradas:

- Snapshot de mercado.
- Estado de simbolo/timeframe.
- Configuracion de estrategia.
- Estado de posiciones relevante.

Salidas:

- `TradeSignal`.
- `SignalDecisionEvent`.

### 5.2 Risk Gate

Responsabilidad:

- Validar que la senal cumple reglas de seguridad.
- Calcular o validar lotaje.
- Rechazar operaciones inseguras con motivo estructurado.
- Bloquear cualquier operacion si `DEMO_ONLY=True` y la cuenta no es demo.
- Bloquear cualquier cuenta real salvo aprobacion explicita futura con whitelist y decision documentada.

Debe verificar:

- SL presente y valido.
- TP presente y valido.
- Spread menor o igual al maximo configurado.
- Lotaje valido para simbolo, paso, minimo y maximo.
- Riesgo individual menor o igual a `MAX_RISK_PER_TRADE_PCT`.
- Drawdown diario dentro del limite.
- Drawdown flotante dentro del limite.
- Trades abiertos totales <= 10.
- Riesgo abierto total <= 5%.
- Sesion y simbolo permitidos.
- Cooldown y limites de frecuencia.
- Snapshot de mercado y senal no obsoletos.
- Auditoria local persistida o encolada antes de permitir ejecucion.

### 5.3 Execution Gate

Responsabilidad:

- Validar compatibilidad MT5 antes de enviar orden.
- Revisar condiciones finales de precio, spread, freeze level, stops level y filling mode.
- Rechazar si la senal envejecio o si el mercado cambio demasiado.

### 5.4 MT5 Order Executor

Responsabilidad:

- Enviar ordenes a MT5 usando el adapter unico definido para el proyecto.
- Verificar resultado del adapter unico de ejecucion y registrar el resultado equivalente de MT5.
- Registrar retcodes y errores.
- No recalcular estrategia ni riesgo.

### 5.5 Position Monitor

Responsabilidad:

- Vigilar posiciones abiertas del magic number configurado.
- Detectar cierres, SL, TP, errores y cambios manuales.
- Emitir eventos de ciclo de vida.

### 5.6 Backtesting

Responsabilidad:

- Ejecutar pruebas reproducibles.
- Registrar parametros, rango de fechas, simbolos, costos, calidad de datos, commit y perfil de broker.
- Producir metricas: profit factor, max drawdown, expected payoff, win rate, Sharpe/Sortino cuando aplique, trades totales y estabilidad por periodo.
- Impedir promocion de estrategias con evidencia insuficiente, sobreajuste o resultados no reproducibles.

### 5.7 Telegram/Logging/Database

Responsabilidad:

- Registrar eventos estructurados localmente.
- Persistir eventos en base de datos cuando exista implementacion.
- Enviar eventos importantes por Telegram.
- Nunca exponer secretos en logs.

## 6. Configuracion Segura

Valores iniciales obligatorios:

```ini
DEMO_ONLY=True
MAX_OPEN_TRADES=10
MAX_OPEN_RISK_PCT=5.0
MAX_RISK_PER_TRADE_PCT=0.5
REQUIRE_SL=True
REQUIRE_TP=True
MAX_DAILY_DRAWDOWN_PCT=3.0
MAX_FLOATING_DRAWDOWN_PCT=5.0
MAX_SPREAD_POINTS_DEFAULT=25
MAX_MARKET_SNAPSHOT_AGE_SECONDS=5
MAX_SIGNAL_AGE_SECONDS=30
MAX_TICK_AGE_SECONDS=5
LIVE_TRADING_APPROVED=False
ALLOWED_ACCOUNT_LOGINS=
ALLOW_PARTIAL_FILL=False
TRADING_HALTED_UNTIL_NEXT_DAY_ON_DD=True
TELEGRAM_ENABLED=False
DATABASE_ENABLED=False
LOG_RETENTION_DAYS=90
MAX_JSONL_FILE_MB=50
TELEGRAM_OUTBOX_RETENTION_DAYS=30
```

Los limites por simbolo pueden ser mas estrictos, nunca mas permisivos sin aprobacion explicita.

## 7. Contratos De Interfaces

Los contratos son canonicos. Si se implementan en MQL5, Python o ambos, deben conservar nombres conceptuales y semantica.

### 7.1 `MarketSnapshot`

Campos:

- `symbol`: string.
- `timeframe`: string o enum.
- `timestamp_utc`: datetime o long.
- `bid`: double.
- `ask`: double.
- `spread_points`: double.
- `digits`: int.
- `point`: double.
- `tick_value`: double.
- `tick_size`: double.
- `volume_min`: double.
- `volume_max`: double.
- `volume_step`: double.
- `stops_level_points`: int.
- `freeze_level_points`: int.

Invariantes:

- `ask >= bid`.
- `spread_points >= 0`.
- `point > 0`.
- `bid > 0` y `ask > 0`.
- `tick_value > 0`.
- `tick_size > 0`.
- `volume_min <= volume_max`.
- `stops_level_points >= 0`.
- `freeze_level_points >= 0`.
- Volumen minimo, maximo y paso deben ser positivos.

### 7.2 `TradeSignal`

Campos:

- `signal_id`: string unico.
- `created_at_utc`: datetime o long.
- `symbol`: string.
- `timeframe`: string o enum.
- `direction`: enum `BUY | SELL`.
- `entry_type`: enum `MARKET | LIMIT | STOP`.
- `entry_price`: double opcional para ordenes pendientes.
- `sl_price`: double obligatorio.
- `tp_price`: double obligatorio.
- `requested_lot`: double opcional.
- `risk_pct`: double opcional.
- `confidence`: double entre 0 y 1.
- `strategy_name`: string.
- `strategy_version`: string.
- `reason`: string corto.
- `metadata_json`: string JSON opcional.

Invariantes:

- `sl_price` siempre obligatorio.
- `tp_price` siempre obligatorio.
- Para `BUY`, `sl_price < entry_reference_price < tp_price`.
- Para `SELL`, `tp_price < entry_reference_price < sl_price`.
- `confidence` entre 0 y 1.
- `signal_id` debe propagarse a logs, base de datos y Telegram.
- Para `MARKET BUY`, `entry_reference_price` es `ask`; para `MARKET SELL`, es `bid`.
- Para `LIMIT` y `STOP`, `entry_price` es obligatorio y es el precio de referencia.
- `metadata_json` debe incluir valores de indicadores/features usados, regimen detectado, version exacta de parametros, barras/candles usados, precio de referencia y motivo estructurado.
- La primera estrategia experimental debe documentar hipotesis, simbolos, timeframes, entradas, salidas, invalidacion de senales, parametros y regimenes esperados antes de implementarse.

### 7.3 `RiskDecision`

Campos:

- `signal_id`: string.
- `accepted`: bool.
- `reject_code`: enum o string.
- `reject_reason`: string.
- `approved_lot`: double.
- `risk_amount_account_currency`: double.
- `open_risk_pct_after_trade`: double.
- `daily_drawdown_pct`: double.
- `floating_drawdown_pct`: double.
- `checks`: lista o JSON con resultados individuales.

Codigos minimos de rechazo:

- `DEMO_ONLY_REAL_ACCOUNT`.
- `MISSING_SL`.
- `MISSING_TP`.
- `HIGH_SPREAD`.
- `INVALID_LOT`.
- `DAILY_DRAWDOWN_LIMIT`.
- `FLOATING_DRAWDOWN_LIMIT`.
- `MAX_OPEN_TRADES`.
- `MAX_OPEN_RISK`.
- `SYMBOL_NOT_ALLOWED`.
- `SESSION_NOT_ALLOWED`.
- `STALE_SIGNAL`.
- `MARKET_DATA_INVALID`.
- `EXECUTION_CONSTRAINT`.
- `INTERNAL_ERROR`.
- `ACCOUNT_TYPE_UNKNOWN`.
- `LIVE_TRADING_NOT_APPROVED`.
- `ACCOUNT_NOT_WHITELISTED`.
- `DAILY_DRAWDOWN_REFERENCE_MISSING`.
- `RISK_CALCULATION_UNCERTAIN`.
- `TERMINAL_TRADE_DISABLED`.
- `ACCOUNT_TRADE_DISABLED`.
- `SYMBOL_TRADE_DISABLED`.
- `MARKET_CLOSED`.
- `INVALID_FILLING_MODE`.

Invariantes:

- Si `accepted=False`, `approved_lot` debe ser 0.
- Si `accepted=False`, `risk_amount_account_currency` debe ser 0.
- `checks` debe incluir chequeos ejecutados, fallidos y no ejecutados marcados como `skipped`.
- Si `requested_lot` y `risk_pct` entran en conflicto, usar el resultado mas conservador o rechazar si no se puede verificar.

### 7.4 `ExecutionRequest`

Campos:

- `signal_id`: string.
- `symbol`: string.
- `direction`: enum `BUY | SELL`.
- `order_type`: enum `MARKET | LIMIT | STOP`.
- `lot`: double.
- `sl_price`: double.
- `tp_price`: double.
- `max_slippage_points`: int.
- `magic_number`: long.
- `comment`: string.

Invariantes:

- Solo puede construirse desde una `RiskDecision.accepted=True`.
- Debe conservar `signal_id`.
- Debe incluir SL y TP.

### 7.5 `ExecutionResult`

Campos:

- `signal_id`: string.
- `sent`: bool.
- `filled`: bool.
- `ticket`: long opcional.
- `retcode`: int.
- `retcode_description`: string.
- `fill_price`: double.
- `requested_lot`: double.
- `filled_lot`: double.
- `error_message`: string.
- `timestamp_utc`: datetime o long.
- `order_ticket`: long opcional.
- `deal_ticket`: long opcional.
- `position_ticket`: long opcional.
- `request_id`: long opcional.
- `last_error`: int.
- `server_comment`: string.
- `execution_latency_ms`: long.
- `account_margin_mode`: string.
- `filling_mode_used`: string.

### 7.6 `Event`

Campos:

- `event_id`: string unico.
- `schema_version`: string.
- `correlation_id`: string, normalmente igual a `signal_id`.
- `causation_id`: string opcional.
- `idempotency_key`: string unico estable para deduplicar reintentos.
- `sequence_number`: long monotonico por sesion cuando sea posible.
- `run_id`: string de sesion/backtest/demo.
- `environment`: enum `BACKTEST | DEMO | LIVE`.
- `timestamp_utc`: datetime o long.
- `severity`: enum `DEBUG | INFO | WARNING | ERROR | CRITICAL`.
- `module`: string.
- `event_type`: string.
- `signal_id`: string opcional.
- `symbol`: string opcional.
- `message`: string.
- `payload_json`: string JSON.

Eventos que deben emitirse:

- Senal generada.
- Senal aceptada.
- Senal rechazada.
- Orden enviada.
- Orden rechazada por MT5.
- Orden ejecutada.
- Posicion cerrada.
- Limite de drawdown alcanzado.
- Intento bloqueado por `DEMO_ONLY`.
- Error de Telegram.
- Error de base de datos/logging.
- Bot iniciado.
- Bot detenido.
- Configuracion cargada.
- Configuracion rechazada.
- Cuenta demo verificada.
- Cuenta no determinable.
- Execution Gate acepto/rechazo.
- Senal obsoleta rechazada.
- Evento persistido.
- Evento encolado por fallo de base de datos.
- Cola de Telegram saturada.
- Reintento de Telegram programado.
- Retencion/rotacion de logs ejecutada.

### 7.7 `BacktestRunConfig`

Campos:

- `run_id`: string unico.
- `strategy_name`: string.
- `strategy_version`: string.
- `symbols`: lista.
- `timeframes`: lista.
- `start_date`: date.
- `end_date`: date.
- `initial_balance`: double.
- `spread_model_json`: string JSON.
- `commission_model_json`: string JSON.
- `slippage_model_json`: string JSON.
- `data_source`: string.
- `parameters_json`: string JSON.
- `code_commit`: git SHA exacto.
- `backtest_engine`: enum `MT5_STRATEGY_TESTER | PYTHON_ENGINE`.
- `engine_version`: string.
- `mt5_build`: string opcional.
- `modeling_mode`: string, por ejemplo `real_ticks`, `every_tick`, `ohlc`.
- `timezone`: string.
- `random_seed`: int opcional, obligatorio si hay aleatoriedad.
- `data_fingerprint`: hash o manifest inmutable del dataset usado.
- `broker_profile_json`: JSON con digits, point, tick_value, tick_size, contract_size, stops_level, freeze_level y volumen por simbolo.
- `cost_model_json`: JSON estructurado con spread, comision, swap, slippage y fuente de estimacion.

### 7.8 `BacktestResult`

Campos:

- `run_id`: string.
- `net_profit`: double.
- `profit_factor`: double.
- `max_drawdown_pct`: double.
- `daily_max_drawdown_pct`: double.
- `trades_total`: int.
- `win_rate_pct`: double.
- `expected_payoff`: double.
- `sharpe`: double opcional.
- `sortino`: double opcional.
- `recovery_factor`: double opcional.
- `notes`: string.
- `avg_win`: double.
- `avg_loss`: double.
- `payoff_ratio`: double.
- `max_consecutive_losses`: int.
- `exposure_time_pct`: double.
- `monthly_returns_json`: string JSON.
- `regime_breakdown_json`: string JSON.
- `mae_mfe_summary_json`: string JSON.
- `parameter_sensitivity_json`: string JSON.
- `artifact_dir`: string.
- `equity_curve_path`: string.
- `trades_path`: string.
- `events_path`: string.
- `config_snapshot_path`: string.
- `report_path`: string.
- `created_at_utc`: datetime o long.
- `status`: enum `PASS | FAIL | INCONCLUSIVE`.
- `rejection_reason`: string.
- `result_fingerprint`: string.

## 8. Flujo De Decision

1. Capturar `MarketSnapshot`.
2. Strategy Engine genera `TradeSignal` o no emite nada.
3. Logging persiste o encola localmente la senal candidata.
4. Risk Gate valida invariantes y limites.
5. Si rechaza, registrar motivo y enviar Telegram si severidad lo amerita.
6. Si acepta, persistir o encolar localmente la `RiskDecision`.
7. Si la auditoria local falla, bloquear sin construir `ExecutionRequest`.
8. Si la auditoria local esta confirmada, construir `ExecutionRequest`.
9. Execution Gate valida restricciones finales de MT5.
10. Executor envia orden.
11. Registrar `ExecutionResult`.
12. Position Monitor sigue el ciclo de vida.

## 9. Reglas De Seguridad Detalladas

### 9.1 Demo Only

- El valor por defecto es `DEMO_ONLY=True`.
- Si `DEMO_ONLY=True`, el bot debe verificar el tipo de cuenta antes de operar.
- Si la cuenta no es demo, emitir evento `CRITICAL` y bloquear operaciones.
- La operacion en cuenta real esta fuera del alcance inicial.
- Aunque `DEMO_ONLY=False`, el bot debe bloquear cuentas reales salvo que `LIVE_TRADING_APPROVED=True`, `ACCOUNT_LOGIN` este en `ALLOWED_ACCOUNT_LOGINS` y exista una decision de arquitectura aprobatoria en `docs/decisions/`.
- Si no se puede determinar `ACCOUNT_TRADE_MODE`, `ACCOUNT_LOGIN` o servidor, rechazar con evento `CRITICAL`.

### 9.2 SL/TP

- SL y TP son obligatorios para toda operacion.
- Deben respetar direccion, distancia minima del simbolo y precision de digitos.
- No se permite abrir primero y modificar despues para agregar SL/TP.
- SL/TP deben normalizarse a `digits`/`tick_size` sin reducir proteccion ni aumentar riesgo.
- Si la normalizacion invalida la distancia minima o aumenta el riesgo por encima del limite, rechazar.

### 9.3 Spread

- Cada simbolo debe tener limite de spread.
- Si no existe limite especifico, usar `MAX_SPREAD_POINTS_DEFAULT`.
- El spread se valida en Risk Gate y nuevamente en Execution Gate.
- Si no hay configuracion especifica ni default valido, rechazar.
- Execution Gate debe recalcular spread con tick actual, no reutilizar solo el snapshot aprobado.

### 9.4 Lotaje

- El lotaje debe respetar `volume_min`, `volume_max` y `volume_step`.
- El lotaje debe normalizarse hacia abajo, no hacia arriba, para no exceder riesgo.
- Si no se puede calcular un lotaje valido, rechazar.
- El riesgo de la operacion candidata no puede exceder `MAX_RISK_PER_TRADE_PCT`.

### 9.5 Drawdown

- Drawdown diario se calcula contra la equity al inicio del dia broker, persistida como referencia diaria obligatoria.
- Drawdown flotante se calcula con equity actual contra balance o high-water mark configurado.
- Al superar limites, bloquear nuevas operaciones y emitir evento importante.
- La referencia diaria por defecto es la equity al inicio del dia broker.
- Si no se puede capturar o persistir la referencia diaria, bloquear nuevas operaciones con `DAILY_DRAWDOWN_REFERENCE_MISSING`.
- Una vez alcanzado el limite de drawdown diario, bloquear nuevas operaciones hasta el siguiente dia broker o hasta reinicio manual auditado, segun lo mas restrictivo.

### 9.6 Exposicion

- Maximo 10 trades abiertos.
- Riesgo abierto total maximo 5%.
- El riesgo abierto incluye posiciones existentes y la operacion candidata.
- `open_trades_after_candidate` debe ser <= `MAX_OPEN_TRADES`; si ya existen 10 trades abiertos, cualquier nueva apertura se rechaza.
- Riesgo abierto = perdida potencial hasta SL de posiciones abiertas y ordenes pendientes gestionadas por el bot, mas la candidata, expresada como porcentaje de equity actual.
- Si tick value, tick size, divisa de beneficio, SL o conversion no son confiables, rechazar con `RISK_CALCULATION_UNCERTAIN`.

### 9.7 Ejecucion MT5

- El executor debe usar un unico adapter de ejecucion.
- Por defecto, el adapter usa `MqlTradeRequest` + `OrderSend` para control explicito y auditoria completa.
- Si se usa `CTrade`, debe estar encapsulado en el mismo adapter y registrar request/result equivalentes.
- Solo se consideran exitosos `TRADE_RETCODE_DONE`, `TRADE_RETCODE_PLACED` para pendientes y `TRADE_RETCODE_DONE_PARTIAL` si `ALLOW_PARTIAL_FILL=True`.
- Retcodes como `REQUOTE`, `PRICE_CHANGED`, `PRICE_OFF`, `INVALID_STOPS`, `INVALID_VOLUME`, `INVALID_FILL`, `MARKET_CLOSED`, `TRADE_DISABLED`, `NO_MONEY` y `TOO_MANY_REQUESTS` deben emitir evento estructurado.
- Reintentos deben ser finitos, usar el mismo `signal_id`, recapturar snapshot y repetir validacion de spread, stops, freeze y riesgo aplicable.
- Para BUY market: `SL <= Bid - stops_level*point` y `TP >= Bid + stops_level*point`.
- Para SELL market: `SL >= Ask + stops_level*point` y `TP <= Ask - stops_level*point`.
- Para pendientes, validar distancia desde precio pendiente y precio actual segun tipo.
- Si `SYMBOL_TRADE_STOPS_LEVEL` o `SYMBOL_TRADE_FREEZE_LEVEL` no pueden leerse, rechazar con `EXECUTION_CONSTRAINT`.
- No enviar modificaciones dentro de `freeze_level`; si la operacion requiere modificacion inmediata, bloquear.
- Execution Gate debe rechazar si trading algoritimico, trading de cuenta o trading del simbolo no esta permitido.
- Antes de operar, el simbolo debe existir, estar seleccionado con `SymbolSelect(symbol, true)`, tener tick reciente via `SymbolInfoTick`, `bid > 0`, `ask > 0`, `ask >= bid` y propiedades de trading validas.
- Execution Gate debe leer `SYMBOL_FILLING_MODE` y seleccionar un modo permitido; si no hay modo compatible, rechazar con `INVALID_FILLING_MODE`.
- `magic_number` debe ser obligatorio, positivo, estable por estrategia/simbolo/timeframe y configurable.
- El comentario MT5 debe incluir prefijo corto y `signal_id` truncado, sin secretos ni JSON largo.
- El bot debe detectar cuenta hedging vs netting/exchange. En netting, una senal opuesta no puede abrirse como posicion independiente sin politica explicita de cierre, reduccion o reversion.
- Execution Gate debe rechazar si no hay conexion (`TERMINAL_CONNECTED=False`) o si el tick es mas viejo que `MAX_TICK_AGE_SECONDS`.

## 10. Telegram

Eventos importantes:

- Bloqueo por cuenta real en modo demo.
- Rechazo por drawdown.
- Rechazo por maximo riesgo abierto.
- Orden enviada.
- Orden ejecutada.
- Error critico de ejecucion.
- Cierre de posicion.
- Inicio/detencion del bot.

Reglas:

- Telegram desactivado por defecto.
- Tokens deben venir de variables de entorno o archivo local ignorado.
- No registrar token completo.
- Si Telegram falla, no debe detener el EA salvo que se configure explicitamente.
- Por defecto Telegram enviara eventos `WARNING`, `ERROR` y `CRITICAL`, ademas de `ORDER_SENT`, `ORDER_FILLED`, `POSITION_CLOSED`, `BOT_STARTED` y `BOT_STOPPED`.
- Los mensajes de Telegram deben pasar por una outbox local duradera.
- Cada mensaje debe tener `telegram_message_id`, `event_id`, `idempotency_key`, `status`, `attempt_count`, `next_retry_at_utc` y `last_error`.
- Los reintentos deben usar backoff exponencial con limite maximo.
- Errores HTTP 429 deben respetar `retry_after` si existe.
- Tokens, chat IDs, account numbers, nombres de servidor, rutas locales e identificadores personales deben tratarse como sensibles.
- Logs y mensajes de Telegram deben pasar por una funcion de redaccion que oculte valores completos y solo permita sufijos parciales cuando sea necesario.

## 11. Logging Y Base De Datos

Formato minimo: JSON Lines local.

Base de datos prevista: SQLite para investigacion/local y adaptador posterior para otro backend si se requiere.

Antes de construir o enviar una `ExecutionRequest`, el evento de senal generada y la decision del Risk Gate deben haberse escrito correctamente en JSONL local o en una cola duradera local. Si no se puede persistir ni encolar el evento, el sistema debe fallar cerrado y no abrir operaciones.

JSONL debe escribirse en UTF-8, una linea valida por evento, con timestamp UTC ISO-8601 y `payload_json` serializable. La ruta por defecto sera `data/logs/events-YYYY-MM-DD.jsonl`. La escritura debe ser append-only. Si se detecta una linea corrupta, no debe sobrescribirse el archivo; debe emitirse un evento de error y continuar en un nuevo archivo si es posible.

SQLite debe incluir como minimo tablas `events`, `telegram_outbox` y `delivery_attempts`. `events.event_id` e `events.idempotency_key` deben ser unicos. La base debe usar migraciones versionadas y modo WAL cuando este disponible. JSONL sigue siendo el registro local minimo aunque SQLite este habilitado.

La retencion por defecto sera configurable con `LOG_RETENTION_DAYS`, `MAX_JSONL_FILE_MB` y `TELEGRAM_OUTBOX_RETENTION_DAYS`. No se debe borrar informacion de auditoria de operaciones sin exportacion o confirmacion explicita.

Todo evento debe incluir:

- timestamp UTC.
- modulo.
- severidad.
- tipo.
- `signal_id` cuando aplique.
- motivo humano legible.
- payload estructurado.

## 12. Backtesting Y Validacion

Antes de considerar una estrategia operable se requiere:

- Backtest in-sample.
- Backtest out-of-sample.
- Separacion train/validation/test si hay ajuste de parametros.
- Prueba walk-forward si hay optimizacion.
- Monte Carlo sobre secuencia de trades y/o retornos.
- Prueba de sensibilidad a spread y slippage.
- Revision de meses negativos y rachas de perdidas.
- Reporte con parametros exactos.
- Forward test en demo o shadow mode antes de habilitar ejecucion demo real.

### 12.1 Strategy Promotion Gate

Una estrategia solo puede pasar a demo ejecutable si cumple todos los puntos:

- Al menos 200 trades historicos o justificacion estadistica de una muestra menor.
- Profit factor OOS > 1.15 despues de spread, comision y slippage.
- Expected payoff OOS positivo.
- Max drawdown OOS menor al limite definido para la estrategia.
- No depender de un unico mes, simbolo o regimen para la mayoria del beneficio.
- Resultados aceptables en sensibilidad de spread/slippage.
- Walk-forward aprobado si hubo optimizacion.
- Forward test o shadow mode con senales auditadas antes de permitir ejecucion demo.

### 12.2 Reproducibilidad Y Datos

Todo backtest debe declarar calidad de datos: tipo de dato usado, proveedor, zona horaria, rango disponible, huecos detectados, ticks/barras descartados, duplicados, fines de semana, cambios de horario/DST y porcentaje de cobertura. Si la calidad no puede verificarse, el resultado queda marcado como no apto para decision operativa.

Los modelos de costos deben serializarse como JSON estructurado, no texto libre. Deben incluir spread fijo/variable, comision por lado o round-turn, swap si aplica, slippage medio/maximo, distribucion usada, moneda de comision y fuente de estimacion.

Toda investigacion con ajuste de parametros debe separar datos en entrenamiento, validacion y prueba final. El periodo de prueba final no puede usarse para seleccionar parametros. Cualquier cambio posterior a ver resultados en test invalida ese test y requiere nuevo periodo holdout.

La prueba walk-forward debe declarar longitud de ventana de entrenamiento, longitud de ventana OOS, paso de avance, parametros candidatos, criterio de seleccion, numero de folds, resultados por fold y resultado agregado. Se debe reportar dispersion entre folds, no solo promedio.

Antes de activar una estrategia debe ejecutarse Monte Carlo sobre secuencia de trades y/o retornos, incluyendo permutacion de orden, bootstrap con reemplazo, stress de spread/slippage y degradacion de fill rate. Reportar percentiles 5/50/95 de equity final, max drawdown, rachas perdedoras y riesgo de ruina.

Todo reporte debe incluir numero de configuraciones probadas, rango completo de parametros evaluados, parametros descartados y motivo, separacion de datasets y registro de cada corrida para evitar cherry-picking.

El reporte cuantitativo debe segmentar resultados por tendencia alcista, tendencia bajista, rango, volatilidad alta/media/baja, sesiones Asia/Londres/Nueva York/solapes, periodos de noticias si el dataset los identifica y spread normal/ampliado.

Cada estrategia debe compararse contra baselines: no-trade, buy-and-hold si aplica, entrada aleatoria con mismo numero de trades/SL/TP, variante sin filtro principal y variante buy-only/sell-only cuando aplique.

Metricas minimas:

- Trades totales.
- Net profit.
- Max drawdown.
- Daily max drawdown.
- Profit factor.
- Win rate.
- Expected payoff.
- Promedio y maximo de perdida consecutiva.
- CAGR cuando aplique.
- Calmar.
- Recovery factor.
- Payoff ratio.
- Profit/loss promedio.
- MAE/MFE.
- Tiempo en mercado.
- Trades por mes.
- Meses positivos/negativos.
- Skew/kurtosis de retornos.
- Peor dia/semana/mes.
- Percentiles de drawdown.
- Metricas por simbolo/timeframe/sesion.

### 12.3 Causalidad Del Backtest Python (motor 0.2.0)

- Timestamps de barras historicas representan apertura.
- TradeCandidate.available_at_utc es opcional para candidatos externos y
  obligatorio en candidatos generados desde OHLC cerrado: apertura mas duracion
  explicita del timeframe. No se infiere una duracion desconocida.
- La entrada usa primera apertura >= disponibilidad. Maximos/minimos anteriores
  no se usan para salida o MAE/MFE. Sin barra posterior elegible, se rechaza.
- Disponibilidad invalida/anterior al origen o entry_price impuesto en candidatos
  con disponibilidad provoca rechazo auditado.
- Compatibilidad: candidatos externos sin ese campo conservan evento disponible
  en timestamp y use_next_bar_open. Disponibilidad explicita tiene prioridad y
  evita un segundo desplazamiento por esa opcion.
- Metadata conserva origen, disponibilidad y politica de entrada. Reportes del
  motor 0.1.0 deben reevaluarse antes de usarse como evidencia, sin sobrescribirlos.
- Spread cero es valido; ausente, negativo o no finito no se sustituye por cero.
  SpreadEstimate agrega reject_reason; SPREAD_DATA_MISSING/INVALID bloquean fills.
  El maximo configurado sigue siendo inclusivo.
- El reporte de paridad agrega decision_parity_status, evidence_scope,
  full_pipeline_verified y stage_parity_pct. PARITY_INCOMPLETE identifica la
  verificacion parcial. Consumidores que aceptaban PARITY_OK como aprobacion
  integral deben fallar cerrados. ADAPTER_REQUIRED no es implementacion compartida.
- Esto no habilita ejecucion demo/real ni sustituye Risk Gate. Decision y limites:
  docs/decisions/2026-10-05-causal-backtests-and-honest-parity.md.

## 13. Estructura De Repositorio

```text
AGENTS.md
PROJECT_SPEC.md
config/
data/
docs/
scripts/
src/
tests/
```

Detalle esperado:

```text
src/mt5/Experts/
src/mt5/Include/Contracts/
src/mt5/Include/Core/
src/mt5/Include/Strategy/
src/mt5/Include/Risk/
src/mt5/Include/Execution/
src/mt5/Include/Telemetry/
src/mt5/Include/Storage/
src/mt5/Include/Backtesting/
src/python/agi_style_forex_bot_mt5/
tests/mt5/
tests/python/
docs/decisions/
docs/testing/
```

## 14. Roadmap Por Fases

### Fase 0: Preparacion Multiagente

- Crear `AGENTS.md`.
- Crear `PROJECT_SPEC.md`.
- Crear estructura base.
- Revisar documentos con subagentes.

### Fase 1: Contratos Y Configuracion

- Implementar tipos/structs base.
- Implementar carga de configuracion segura.
- Tests de invariantes.

### Fase 2: Risk Gate

- Validar SL/TP, spread, lotaje, drawdown, exposicion y cuenta demo.
- Tests unitarios de rechazo.

### Fase 3: Ejecucion MT5

- Implementar executor seguro.
- Manejar retcodes.
- Tests en Strategy Tester/demo.

### Fase 4: Estrategia

- Documentar hipotesis, reglas exactas, salidas y regimenes antes de programar senales.
- Implementar primera estrategia experimental.
- Validar con backtesting.
- Ejecutar shadow mode antes de demo ejecutable.

### Fase 5: Observabilidad

- Logs JSONL.
- Telegram.
- Persistencia SQLite.

### Fase 6: Backtesting Avanzado

- Ampliar reportes reproducibles ya obligatorios desde Fase 4.
- Walk-forward.
- Sensibilidad a costos.

## 15. Criterios De No Operacion

El bot no debe operar si:

- `DEMO_ONLY=True` y la cuenta es real.
- No se puede determinar el tipo de cuenta.
- No hay SL.
- No hay TP.
- Spread excede limite.
- Lotaje es invalido.
- Drawdown diario excede limite.
- Drawdown flotante excede limite.
- La nueva apertura dejaria mas de 10 trades abiertos.
- Riesgo abierto excede 5%.
- Snapshot de mercado es invalido.
- Error interno impide auditar la decision.

## 16. Pendientes Para Implementacion Futura

- Definir estrategia inicial exacta.
- Elegir esquema final de persistencia.
- Definir formato de presets `.set`.
- Definir matriz de simbolos permitidos.
- Definir versionado de parametros.
- Definir CI para validaciones Python y lint documental.

## 17. Contratos De Correccion Y Validacion Compartida (2026-10-05)

Esta ampliacion toca estrategia, riesgo paper, observabilidad y backtesting;
no autoriza ejecucion demo ni real y no sustituye el Strategy Promotion Gate.

- `data.strategy_features`: preparacion causal versionada `closed_bar_features_v1`.
  OHLC tiene timestamp de apertura; una barra solo esta disponible al cierre.
  El adaptador MT5 excluye la barra en formacion, declara M5 explicitamente y
  el builder rechaza campos ausentes/no finitos. Swings confirmados requieren
  dos barras posteriores; soporte/resistencia y compresion usan historia previa.
  Las sesiones son bandas UTC fijas, no calendarios DST del broker certificados.
- Las seis estrategias y el ensemble version `0.2.1` pasan la direccion al
  scoring. La calidad del ensemble es media de votantes de la direccion elegida;
  si falta un score valido no se inventa. `calibration.decision_policy` aplica
  identicos thresholds y overlays en backtest y forward; exige todos los
  componentes y scores finitos 0..100. Perfiles/archivos invalidos no caen a otro
  perfil silenciosamente. No se han relajado umbrales.
- `core.decision.SharedDecisionPipeline.evaluate(DecisionContext)` ordena
  estrategia, perfil, estabilidad, construccion de senal, persistencia, riesgo,
  ML, ranking, portfolio, riesgo dinamico, limites paper y ajuste de volumen.
  Contexto exige estado completo con timestamps, referencias de riesgo,
  posiciones, calidad broker y correlacion cuando hay exposicion. Cada etapa
  produce passed/rejected/error/skipped; no hay defaults que simulen evidencia.
  El volumen se redondea hacia abajo y el ajuste conserva riesgo preexistente.
  SL/TP comparten ATR medido, piso100 puntos, stops broker y RR1.8 existentes.
- `ForwardShadowBot` usa ese nucleo y guarda el resultado completo antes del
  fill paper. Recibe reloj y proveedor explicito de evidencia broker/correlacion.
  `PAPER_ALLOW_DISABLED_ML=False` por defecto; True permite investigar sin modelo
  solo paper, auditandolo. ML_ERROR siempre bloquea; un modelo necesita fecha de
  disponibilidad no posterior a la decision. Ranking actual es por candidato,
  sin afirmar competencia top-N entre todos los simbolos.
- `paper_trading.decision_state` persiste baseline solo en libro vacio y deriva
  balance/equity de PnL realizado/flotante, con todas las posiciones cotizadas.
  Conserva referencia y halt diario UTC. Historia faltante, metadata ambigua,
  referencia overnight ausente o fallo de persistencia bloquean entradas.
  El store requiere un unico escritor; no se inventa equity de medianoche.
- Trades paper nuevos llevan `metadata.pnl_basis=APPROVED_LOT_UNSCALED_V1` y
  `pnl_formula_version=paper_pnl_approved_lot_v1` al cierre. Lot ya fue ajustado;
  profit/raw_pnl/scaled_paper_pnl son el mismo PnL neto, sin segundo multiplicador.
  Distancia/riesgo iniciales se conservan para BE/trailing y R. Un gap de SL usa
  precio observado adverso. Evidencia legacy no se reescribe ni se adopta para
  nuevas entradas sin reconciliacion explicita.
- `backtesting.decision_replay.replay_decisions` reproduce contextos completos
  mediante FrozenClock y el mismo nucleo, con auditoria obligatoria del resultado.
  Este alcance es `RECORDED_DECISION_REPLAY`, no verificacion de rentabilidad ni
  simulacion completa de portfolio. El motor OHLC `0.3.1` de candidatos
  independientes sigue declarando `full_risk_pipeline_applied=False` y
  `operationally_eligible=False`; sus metricas no promueven una estrategia.
- `InstrumentRegistrySnapshot` captura solo symbol_info via cliente inyectado,
  con mapa explicito canonical->broker, fecha UTC, hash metadata y hash envelope.
  Es inmutable y no sobrescribe evidencia; hash demuestra integridad, no origen
  autentico ni validez historica. Tick value/moneda/condiciones historicas siguen
  requiriendo evidencia. CLI `build-instrument-registry` requiere mapa JSON y
  destino nuevo, solo initialize/symbol_info/shutdown; nunca account u ordenes.
- `RunManifest` version1.1 agrega hashes de fuentes Python/MQL/scripts y metadata
  o snapshot de instrumentos a la identidad. IDs cambian respecto1.0; campos
  anteriores permanecen. Backtest batch incluye config efectiva, settings y
  archivos historicos; overlays participan por contenido resuelto.
- Walk-forward: test windows disjuntas, validacion selecciona parametros y test
  solo evalua el elegido. API programatica agrega warmup_size/purge_size
  (compatibilidad defaults0/0); calendario agrega warmup_bars=250/purge_bars=1.
  `DataFrame.attrs['walk_forward_context']` identifica warmup y tramo evaluable.
  No cuentan entradas en warmup, salidas fuera de ventana ni cierres truncados
  por fin de datos; metricas se recalculan del tramo valido. Costes no son
  parametros optimizables para mejorar scores; escenarios se evaluan separados.
- Los datos EURUSD/GBPUSD/USDJPY M5 ya inspeccionados (febrero-mayo2026) son
  diagnostico/desarrollo, nunca holdout final. Toda evidencia anterior a estas
  correcciones queda historica y no certifica el comportamiento nuevo.

### 17.1 Contrato De Replay Estatal Y Correcciones De Riesgo

- `backtesting.stateful_replay` acepta eventos cronologicos con cotizaciones
  explicitas, barras cerradas y evidencia broker/correlacion disponible entonces.
  Construye el libro desde capital simulado demo y un directorio nuevo; no adopta
  posiciones ni equity inventados de un contexto externo. Usa el mismo builder,
  nucleo de decisiones, ledger y manager del forward. No conecta MT5 ni Telegram.
  El modelo ML se inyecta explicitamente; no puede cargar artefactos locales
  posteriores al periodo. Metadata de instrumentos debe coincidir y estar
  disponible antes de cada evento. Integridad por hash no autentica su origen.
- Scope `STATEFUL_EXPLICIT_QUOTE_REPLAY`: no interpolar trayectorias intrabar
  desde OHLC ni presentar una secuencia inventada como ticks observados. Eventos
  sin cotizaciones frescas para posiciones abiertas no autorizan decisiones.
  Una referencia diaria con exposicion overnight solo puede capturarse con
  cotizaciones completas en el instante exacto de medianoche UTC; si falta,
  bloquear y declarar evidencia incompleta. No reescribir referencias ni halts.
- Auditoria durable del evento, senal y decision precede cualquier apertura
  paper. Resultados incluyen identidad de fuentes, inputs, configuracion y
  metadata, decisiones y trayectoria del patrimonio. El reporte no declara
  promocion, rentabilidad validada ni habilita ejecucion real/demo.
- `PaperPositionManager` reconcilia lotaje despues de fill: presupuesto incluye
  distancia real a SL, slippage de salida y comision completa. Redondea hacia
  abajo, nunca aumenta volumen aprobado, y rechaza si queda bajo minimo. Audita
  y relee reconciliacion antes de insertar. Gaps pueden exceder el presupuesto
  simulado de un stop; no se promete un limite absoluto de perdida.
- Idempotencia paper identifica senal y simbolo sin depender de direccion;
  reutilizar identidad con intencion diferente (direccion, proteccion, version,
  configuracion o metadata relevante) bloquea. Un reintento identico despues de
  BE conserva el trade original. Evidencia legacy ambigua requiere reconciliar.
- Precios de proteccion y fills deben respetar `tick_size`, no solo `digits` ni
  `point`. Normalizacion adversa de fill participa en riesgo; niveles off-grid
  se rechazan antes de abrir cuando no pueden normalizarse de forma consistente.
- Observabilidad distingue `historical_drawdown_amount` monetario de drawdown
  diario/flotante porcentual del ledger. Metricas requieren valuation fresca y
  fingerprint del libro actual; ausencias o discrepancias son UNKNOWN/null.
  Una perdida monetaria historica no constituye por si sola un halt diario.
- Payloads de auditoria se redactan como estructuras antes de serializar JSON;
  no se aplican expresiones de texto al JSON serializado que puedan corromper
  decimales o romper su lectura. Se conservan controles de secretos existentes.
- Gate paper `stable_shadow_gate_v2` exige perfil coincidente, flags booleanos
  exactos, conteos enteros no negativos y metricas numericas finitas; estados
  ausentes/desconocidos/insuficientes no equivalen a aprobacion. Se conservan
  umbrales previos y se exige estado admitido de MC, stress, WFA y costes. Un
  archivo preferido invalido bloquea; no se sustituye por uno anterior. El gate
  no autentica por si solo la procedencia de artefactos legacy.
- Transporte de replay: JSONL con un evento por linea, claves unicas, timestamps
  con zona horaria y valores numericos finitos. Barras canonicas usan `volume`
  y `spread_points`. No ordenar, completar ni reinterpretar datos ambiguos.
  `scripts/replay_stateful_quotes.py` requiere config, instrumentos, costes,
  capital simulado y modelo explicitamente; `--without-ml` requiere la opcion
  paper correspondiente. `MLFilter.disabled_for_research()` no lee modelos
  locales ni cambia las condiciones del gate.
- Mientras esta release carezca de Strategy Promotion Gate y evidencia de
  ejecucion aprobados, el adapter MT5 no construye requests ni invoca
  `order_check`/`order_send`. `ExecutionEngine.execute` devuelve rechazo incluso
  con riesgo aceptado y booleano audit_confirmed. `SHADOW_MODE_BLOCKED` identifica
  shadow; `EXECUTION_NOT_RELEASED` impide activarlo cambiando ese flag. No existe
  switch de aprobacion, whitelist ni token que habilite esta release. Las APIs
  de lectura y firmas se conservan; antiguos callers que esperaban envio reciben
  rechazo explicito. Una futura release necesita decision de arquitectura y
  evidencia completa antes de implementar capacidad ejecutable demo.
- Caller forward/replay no reevalua para apertura una identidad de senal que
  ya tenga trade paper persistido (abierto o cerrado). Registra
  `CANDIDATE_ALREADY_TRADED`; conserva la proteccion estricta de intencion del
  manager para llamadas directas. Una senal rechazada sin trade puede volver a
  evaluarse con observaciones frescas y auditoria nueva. La identidad incluye
  simbolo, barra cerrada y perfil; los limites siguen aplicandose entre barras.
- `TelemetryDatabase.insert_paper_trade_event` acepta `timestamp_utc` opcional;
  manager pasa el instante observado al abrir/modificar/cerrar. El tiempo de
  insercion puede conservarse separado y no alimenta decisiones historicas.
  Fallos de auditoria postfill se propagan como `PaperAuditError`, detienen el
  replay y marcan `audit_complete=False` aunque se pueda guardar el evento halt.
- Metricas de trades cerrados incluyen el capital inicial antes del primer
  resultado, incluso sin barras auxiliares. Si coincide con el primer cierre,
  la curva conserva dos filas del mismo timestamp UTC, baseline primero; no
  inventa un instante anterior. Agrupa cierres simultaneos y conserva todos los
  timestamps de cierre entre barras. Retornos de peor dia/semana/mes
  incluyen el primer periodo frente al capital inicial; no se descarta con
  pct_change. Recovery factor divide beneficio neto por el maximo drawdown
  monetario observado, no por un porcentaje multiplicado por capital inicial.
  Estas metricas no sustituyen la trayectoria mark-to-market del replay estatal.
- El consolidado `validation-report` es un informe observacional, nunca una
  autorizacion de promocion o ejecucion. Evidencia ausente, JSON ambiguo,
  numeros no finitos y clasificaciones desconocidas no equivalen a aprobacion.
  Conserva umbrales y firmas; registra disponibilidad/calidad por seccion y
  flags explicitos de ejecucion/promocion deshabilitadas. Arrays producidos por
  el registry/mix de investigacion solo son informacion, no autorizaciones.
- El diagnostico de candidatos conserva la configuracion efectiva, rol de los
  datos inspeccionados y estadistica de spreads suministrados. Un spread cero
  puede ser una observacion o evidencia incompleta; no se considera coste
  verificado ni se sustituye silenciosamente. Las metricas conservan los
  supuestos declarados y no autorizan promocion.

### 17.2 Base Nativa De Observacion MQL5

La primera implementacion nativa tiene scope `NATIVE_OBSERVATION_ONLY` y no
implementa una estrategia ni certifica paridad con el motor Python. Su gate de
ejecucion rechaza siempre `EXECUTION_NOT_RELEASED`; no construye requests ni
incluye APIs de trading, red o DLL. No existe flag que active operaciones.

- El EA exige cuenta demo conocida y conexion valida, incluso si alguien
  cambia DEMO_ONLY. No lee ni registra login, servidor, nombre o credenciales.
- Cotizaciones y metadata pasan validacion finita, precios/tick grid, spread,
  volumen y frescura. Cada aceptacion/rechazo es de una observacion de datos,
  nunca de una senal operable.
- Reloj host UTC requiere confirmacion explicita y offset de timestamp del
  broker declarado con intervalo de validez. Defaults desconocidos bloquean
  inicializacion; no se deduce un offset ni se certifica autenticidad temporal.
  Tester se rechaza donde no se pueda preservar esta semantica UTC.
- Auditoria local JSONL UTF8 por sesion con limite de tamano, flush y verificacion
  de lectura; fallo de auditoria aborta inicializacion o detiene observacion.
  Este transporte no se presenta como entrada directa al replay Python.
- Compilacion se realiza en staging separado; no instala el EA ni inicia el
  terminal. Compilar un harness no implica haberlo ejecutado. Runtime, Telegram,
  estrategia nativa y validacion broker quedan pendientes de evidencia propia.

### 17.3 Ciclo Economico Compartido Forward/Replay

`paper_trading.lifecycle.process_paper_cycle(bot, cycle)` es el unico procesador
del ciclo economico paper para `ForwardShadowBot.run` y el replay estatal. Los
callers adquieren datos; el procesador valida, gestiona posiciones, decide,
persiste y valora el libro. No obtiene cotizaciones faltantes por su cuenta.

- Contratos de entrada: `PaperAccountObservation(account, observed_at_utc,
  connected)`, `PaperCandidate(symbol, timeframe, broker_symbol, bars)`,
  `PaperEvidence(observed_at_utc, broker_readiness_score, correlation)` y
  `PaperCycleInput(event_id, observed_at_utc, account_observation, quotes,
  candidates, evidence)`. Se conserva el transporte publico del replay mediante
  conversion a estos contratos; no cambia el significado de sus timestamps.
- `PaperCycleResult` conserva decisiones, rechazos, valuation, trades,
  opened/closed, paused/halted y audit_complete. El metodo publico
  `ForwardShadowBot.process_paper_cycle` delega en el mismo procesador. Las
  pruebas de paridad deben pasar tambien por el `.run` real de forward; llamar
  dos veces al helper no acredita integracion de ambos callers.
- `ForwardShadowSummary` agrega audit_complete, lifecycle_halted y
  paper_state_available. Un almacenamiento ilegible produce open_trades=null,
  nunca cero como sustituto de un libro desconocido; consumidores deben
  comprobar disponibilidad antes de interpretar el contador.
- Cada ciclo exige cuenta demo conocida, conectada, permiso de trading
  explicitamente conocido y datos finitos de capital. Ausencia de moneda,
  identidad o timestamp no se sustituye por valores por defecto. Cambios de
  identidad/moneda observables durante la sesion bloquean; no se registran IDs
  reales ni se atribuye verificacion de servidor a un contrato que no lo expone.
- Se valida el conjunto completo de cotizaciones, incluida toda exposicion
  abierta, antes de mutaciones economicas. La frescura se revalida con el reloj
  operativo antes de cada mutacion/apertura; no se congela el reloj del forward
  para hacer pasar datos caducados. Evidencia de calidad broker exige fecha
  explicita no futura y vigente. Nunca se inventa la fecha de una medicion.
- Se persiste intencion de ciclo antes de mutar y se elimina solo tras auditoria
  completa. Fallo de almacenamiento, auditoria obligatoria o gestion detiene los
  candidatos restantes y deja un latch durable. Un reinicio con ciclo incompleto
  bloquea hasta reconciliacion; la integridad fisica de SQLite no demuestra
  integridad semantica del libro. Los fills ya persistidos siguen visibles aunque
  se revoquen las aprobaciones del ciclo incompleto.
- Los rechazos normales de estrategia no impiden evaluar el siguiente candidato
  con exposicion actualizada. Se conservan gates de recuperacion, microforward,
  estabilidad, riesgo y limites paper. Solo una pausa propia por drawdown diario
  puede expirar, en nuevo dia con ledger/referencia verificados y configuracion
  que permita reanudacion automatica. Una pausa manual o desconocida se conserva.
- Se mantiene la referencia overnight de medianoche UTC exacta del apartado
  anterior. La paridad controlada con fixtures no verifica timing, fills,
  disponibilidad ni procedencia del broker: `full_pipeline_verified=False` y
  `execution_authorized=False` permanecen vigentes.
- Spread derivado de bid/ask/point usa aritmetica decimal de sus representaciones
  declaradas (`spread_points_from_prices`). Se conservan fracciones reales y
  limites; no se redondea al entero ni al umbral. Precios/point invalidos o
  resultados no representables bloquean. El adapter de lectura, normalizacion
  de ticks y validacion de replay comparten esta conversion para evitar que ruido
  binario altere percentiles de spread o decisiones en un limite.
- SL dinamico paper se alinea a tick_size hacia abajo para BUY y hacia arriba
  para SELL, conservador respecto al beneficio simulado y sin aflojar el stop
  existente. Break-even conserva el precio ejecutable de entrada y el riesgo
  inicial no se sustituye por la distancia del stop modificado. Gestion y
  valuation rechazan posiciones OPEN con entrada, SL o TP fuera de la rejilla;
  no reescriben retrospectivamente cierres historicos.

### 17.4 Evidencia Sintetica Monte Carlo Y Stress

Una permutacion o bootstrap de resultados define una secuencia sintetica. No se
puede ordenar despues por los timestamps originales: eso deshace la permutacion
y falsea drawdown y rachas. Tampoco se atribuye un calendario observado a ella.

- `shuffled_metrics` conserva argumentos y devuelve `SequenceMetrics`, con indice
  entero de trade y capital inicial incluido. Conserva metricas economicas de
  resultado, drawdown, profit factor, R y rachas usadas por sus consumidores.
  Metricas dependientes del calendario (Sharpe, Sortino, retornos por periodo)
  permanecen null o mapas vacios. Este cambio de tipo es intencional; callers
  que requieran calendario deben usar trades observados y `calculate_metrics`.
- Monte Carlo exige capital finito positivo, seed entero no negativo,
  iteraciones enteras positivas, metodo admitido y umbral finito en (0, 100].
  Booleanos, NaN, infinito y desbordamientos no producen reportes aprobatorios.
- El campo legacy `risk_of_ruin_pct` conserva su nombre por compatibilidad, pero
  declara su evento como `MAX_PEAK_DRAWDOWN_AT_LEAST_THRESHOLD`: probabilidad
  simulada de alcanzar el umbral de drawdown. Un drawdown del 30% no equivale a
  insolvencia. No se modifica el umbral de clasificacion ni se autoriza ejecucion.
- Stress de costes/concentracion es `POST_TRADE_APPROXIMATION`. Una racha de
  perdidas artificial se agrega al final de la secuencia, sin que fechas
  originales reordenen sus resultados. Omision periodica e haircut fijo se
  denominan `periodic_trade_omission` y `fixed_profit_haircut` respectivamente.
- `entry_delay_one_bar`, `session_shift`, `fill_rate` y `missing_bars` requieren
  replay con quotes explicitos. Sin esa evidencia se reportan `NOT_MODELED`,
  metrics=null y motivo `REQUIRED_EXPLICIT_QUOTE_REPLAY`; no cuentan como pruebas
  ejecutadas ni verificadas. Un haircut no demuestra retraso real de entrada.
- Penalizaciones exigen unidades/costes finitos y coherencia de R. La eliminacion
  de mejores trades usa posiciones de la secuencia, no identidad de objetos.
  Las clasificaciones legacy de costes y concentracion quedan acotadas al
  diagnostico; no sustituyen el Strategy Promotion Gate.
- Reportes v2 conservan entradas normalizadas y hashes de datos/configuracion,
  RunManifest, commit, fuentes, runtime y seed. Configuracion identifica capital,
  umbral y supuestos de costes. Procedencia upstream permanece UNKNOWN salvo
  evidencia explicita. Si se entregan trades y trades_path, trades es la entrada
  efectiva; el hash del archivo es referencia adicional, no prueba de igualdad.
- Consumidores de `StressResult` comprueban status y metrics antes de leer
  resultados. Ausencia de escenarios completos o escenarios no modelados no
  constituye evidencia suficiente. El runner legacy de investigacion declara
  que no ha aplicado parametros diferenciados ni realizado una separacion OOS;
  etiquetar candidatos no demuestra que se hayan probado estrategias distintas.
  Ninguno de esos resultados puede autorizar promocion o ejecucion.

### 17.5 Timestamps Python Sin Frescura Inferida

El adapter Python interpreta timestamps MT5 como UTC conforme a su contrato
publicado. Una diferencia proxima a una hora no demuestra zona horaria ni
frescura: un tick viejo con otro offset produce la misma observacion.

- `normalize_tick_time` conserva firma y diagnosticos, pero ninguna inferencia
  de offset convierte un timestamp futuro en aceptable. Solo una edad observada
  entre cero y max_tick_age_seconds, inclusive, permite status FRESH. Timestamps
  invalidos, ambiguos, futuros o caducados bloquean.
- Las banderas legacy de normalizacion/deteccion y lista de offsets pueden
  proporcionar hints de diagnostico, nunca autorizacion de datos. No se
  persiste una inferencia como offset confirmado ni se altera el timestamp usado
  por riesgo. El antiguo resultado NORMALIZED_FRESH inferido deja de aceptarse
  intencionalmente; la compatibilidad de argumentos no conserva ese fallo.
- Un proveedor que realmente entregue otra base temporal requerira adaptador
  explicitamente verificado, evidencia independiente e intervalo de validez.
  Esta release no lo implementa. El contrato del observador MQL5 es distinto y
  su configuracion no demuestra procedencia temporal de datos Python.
- La frescura contra reloj local no autentica ese reloj ni el origen del tick.
  Datos aparentemente UTC deben seguir pasando coherencia, calidad, auditoria
  y gates de promocion. No se agrega una ruta de ejecucion broker.
