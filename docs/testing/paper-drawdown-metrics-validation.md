# Metricas de drawdown paper por unidad y fecha

Problema corregido: el monitor comparaba drawdown historico en moneda contra
`-3.0` como si fuera porcentaje diario. Una perdida de 4 USD sobre 10000 USD
disparaba un halt del 3%, y la misma historia podia volver a pausar dias futuros.

MetricsCollector recibe `clock` opcional. Lee la baseline, la referencia del dia
UTC y observed_valuation persistidas por build_paper_decision_state. Requiere
valoracion de no mas de 5 segundos, timestamp no futuro, valores finitos,
balance/equity coherentes y trade_state_hash del libro exacto actual.

Campos operativos:

- paper_risk_state_status: VERIFIED o UNKNOWN, con paper_risk_state_reason.
- daily_drawdown_pct: porcentaje no negativo contra equity de inicio del dia.
- floating_drawdown_pct: porcentaje no negativo contra balance paper actual.
- paper_balance, paper_equity, paper_realized_pnl, paper_floating_pnl.
- daily_drawdown_halted: latch diario durable.
- drawdown_paper: alias negativo del porcentaje diario, con
  paper_drawdown_unit=percent; vale null si la evidencia es desconocida.
- historical_drawdown_amount: drawdown historico negativo expresado en moneda,
  con historical_drawdown_currency. Nunca se usa como umbral porcentual.

El PnL abierto valorado al bid/ask forma parte de equity. Un historial legacy,
una referencia ausente, una valoracion vieja/corrupta o un libro modificado desde
la valoracion producen UNKNOWN y valores de riesgo null; no se supone drawdown
cero. El collector es de solo lectura. Los consumidores deben verificar status
antes de interpretar cifras; la ausencia de evidencia no equivale a permiso.

AlertRuleEngine emite PAPER_DAILY_DRAWDOWN ante porcentaje diario verificado de
al menos 3% o latch vigente. Emite PAPER_FLOATING_DRAWDOWN al alcanzar 5%
flotante verificado. Un libro con evidencia paper pero riesgo no verificable
emite PAPER_RISK_DATA_MISSING, distinto de una perdida observada. Una metrica
legacy `drawdown_paper=-4` sin unidad/procedencia no pasa como 4% verificado.

La integracion forward refresca el ledger tras gestion/aperturas y antes de
colectar metricas, incluso sin senales nuevas. Un fallo de refresco debe forzar
UNKNOWN para ese ciclo. El halt diario persiste tras recuperacion de equity;
el historial monetario de dias previos no dispara un nuevo halt al dia siguiente.
El conteo de cierres usa el Clock inyectado y convierte offsets de registros a UTC.

Verificacion:

```powershell
py -3.14 -B -m pytest tests/python/test_paper_drawdown_metrics.py tests/python/test_paper_decision_state.py tests/python/test_shared_decision_core.py tests/python/test_phase9_observability.py tests/python/test_phase8_forward_shadow.py
```

Regresiones incluyen perdida 4 USD (0.04%, sin halt), 300 USD (3%, con halt),
flotante, recuperacion, cambio de dia, stale/future marks, libro cambiado,
datos legacy, NaN/Infinity, unidades y offsets UTC. Importaciones en procesos
limpios de observability, metrics_collector y paper_trading tambien se validaron
para evitar ciclos de imports. Sin operaciones MT5 ni escrituras productivas.
