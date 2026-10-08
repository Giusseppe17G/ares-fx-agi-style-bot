# Estado de decision paper verificable

Modulo: contabilidad paper y entradas al Risk Gate. No envia ordenes ni consulta
MT5. La estrategia y el ejecutor no se modifican aqui.

## API

`paper_trading.decision_state.build_paper_decision_state` recibe:

- `database`: store con get_operational_state/update_operational_state, compatible
  con TelemetryDatabase.
- `trades`: historial completo de PaperTrade, abierto y cerrado.
- `snapshots_by_symbol`: cotizaciones y metadata para todos los simbolos abiertos.
- `account_template`: identidad/demo/moneda verificadas por el llamador.
- `now_utc`: datetime con zona horaria.
- `max_snapshot_age_seconds=5`, `audit_confirmed=False` y
  `max_daily_drawdown_pct=3.0` (no admite un limite mas permisivo).

Devuelve PaperDecisionState con account, risk_state, initial_balance,
realized_pnl, floating_pnl, operational_day y portfolio_open_trades. Esta ultima
tupla conserva el payload de cada abierto con risk_pct recalculado sobre equity
actual y riesgo conservador, ademas de risk_amount_current; no reutiliza un
porcentaje calculado contra capital historico. Cualquier incertidumbre produce
PaperStateError con detail.reject_code; el llamador debe auditarlo y bloquear
nuevas entradas. No convertir la excepcion en un estado vacio.

## Contabilidad y procedencia

La primera corrida puede fijar initial_balance desde account_template.balance
solo cuando el historial esta vacio. Se persiste bajo
`operational_state.paper_decision_state_v1`. Si ya hay trades y falta baseline,
se bloquea con PAPER_CAPITAL_REFERENCE_MISSING. Reiniciar el bot o cambiar el
balance mostrado por el broker no reinicia capital ni borra perdidas paper.
No se persiste el login, servidor ni credenciales del template.

Los trades nuevos deben llevar
`metadata.pnl_basis=APPROVED_LOT_UNSCALED_V1`. El lot guardado es el
volumen final aprobado: el mark-to-market no aplica otro multiplicador. Los
campos paper_risk_multiplier/risk_multiplier deben ser 1 y multiplier_applied
debe ser False. Los trades cerrados requieren formula
`paper_pnl_approved_lot_v1`, con profit/raw_pnl/scaled_paper_pnl coherentes.
Los registros legacy o multiplicados requieren reconciliacion explicita y
fallan con PAPER_PNL_PROVENANCE_UNVERIFIED; no se reescriben ni se eliminan.

Balance paper = baseline + suma de PnL cerrado. Equity paper = balance + PnL
marcado de todos los abiertos. BUY marca al bid; SELL al ask. Se usa
movimiento/tick_size*tick_value*lot menos la comision persistida una vez. La
moneda de tick_value debe haber sido validada por el proveedor del snapshot;
esta API no infiere conversiones de divisas. La identidad/demo del template
se conserva y margin_free se fija a 0, ya que no se modela margen paper.

Las posiciones se incluyen completas en RiskRuntimeState. Los tickets son
identificadores sinteticos deterministas derivados del paper_trade_id; nunca
son tickets MT5. magic_number=0 identifica aqui un estado exclusivamente paper,
que no debe enviarse a un adapter de ejecucion. Riesgo abierto por posicion =
maximo del riesgo inicial persistido y la distancia del mark actual al SL,
valorada con metadata observada. Esta eleccion es conservadora despues de
break-even/trailing. No reduce riesgo usando multiplicadores adicionales.

## Referencias, reinicio y fallos

Las referencias diarias usan dia UTC, son persistidas/releidas antes de devolver
un estado aceptable y no se resetean entre scans o reinicios. Un nuevo dia puede
reconstruir el saldo inicial solo si ningun trade atraviesa medianoche; si hay
exposicion overnight y falta equity de medianoche, se bloquea con
DAILY_DRAWDOWN_REFERENCE_MISSING. Nunca se toma el mark actual como si fuera una
cotizacion historica de medianoche.

El ledger conserva observed_valuation con balance, equity, realizado, flotante,
porcentajes de drawdown, timestamp y trade_state_hash. El hash cubre las
condiciones economicas/estado de todo el libro; cambios de posicion, SL/TP,
lot, cierre o PnL invalidan una valoracion previa aunque su timestamp sea reciente.
Las metricas requieren refrescar esta valoracion despues de gestionar/abrir
trades. El llamador debe refrescar incluso si no pudo generar features nuevas.

Si se alcanza el limite diario, el halt se persiste para todo el dia y produce
KillSwitchState hasta la siguiente medianoche. Una recuperacion posterior de
equity no libera el halt. Equity no positiva tambien persiste el halt antes de
rechazar. Los dias previos se conservan. Un indice duradero de trades detecta
historias truncadas, IDs duplicados, cambio de condiciones economicas y cierres
reabiertos/modificados. Retroceso de reloj o cambio de moneda bloquean.

Todos los abiertos requieren MarketSnapshot coincidente, fresco y finito, lot
compatible y SL/TP vigentes. Si ya alcanzo una salida, el lifecycle debe ser
reconciliado antes de habilitar entradas. No hay sustituciones de tick_value,
tick_size ni de cotizaciones faltantes. El audit_confirmed recibido se preserva;
su default es False y la persistencia de referencias no equivale a persistencia
de senal/decision. El pipeline debe confirmar sus propios eventos duraderos.

## Verificacion

```powershell
py -3.14 -B -m pytest tests/python/test_paper_decision_state.py
```

46 casos: seed vacio, baseline faltante, realizado/flotante, BUY/SELL, comisiones,
reinicio real SQLite, referencias diarias, halt pegajoso/recuperacion, rollover,
overnight sin evidencia, metadata ausente/invalida/obsoleta, provenance legacy,
duplicados/truncamiento/cambio de historia, volumen/pasos, cero equity,
10 posiciones y riesgo abierto >5% bloqueados por PortfolioGuard, persistencia
real de trades sin perder pnl_basis por redaccion y fallos de escritura/readback.
Todas las escrituras usan temporales; no se consulta MT5 ni datos productivos.

## Limites pendientes

El store actual es para un unico escritor forward-shadow por base de datos; las
operaciones publicas de TelemetryDatabase no ofrecen compare-and-swap entre
varios procesos. No iniciar varios escritores sobre el mismo ledger. Una
revision futura debe ofrecer una transaccion de ledger/entrada si se requiere
concurrencia. La captura de equity a medianoche con posiciones abiertas y la
migracion auditada de historia legacy siguen requiriendo evidencia explicita.
La integracion del pipeline y el contrato de PnL del manager corresponden a los
agentes propietarios de esos modulos.
