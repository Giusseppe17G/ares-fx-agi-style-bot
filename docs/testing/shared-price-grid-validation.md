# Precios ejecutables en paper y replay

Alcance: riesgo, simulacion de ejecucion y reproducibilidad; no envia ordenes.

`core.price_grid.snap_price_to_tick(price, tick_size, *, rounding)` requiere
precios positivos finitos y direccion `up`/`down`. `adverse_fill_price` aplica
deslizamiento en puntos con aritmetica Decimal y alinea usando `tick_size`, que
puede ser mayor que `point`. La precision de display no sustituye al incremento
ejecutable del broker. Referencia oficial:
https://www.mql5.com/en/book/automation/symbols/symbols_point_tick

La politica de senales conserva ATR, piso de 100 puntos, ratio 1.8 y el
redondeo inicial a digits. Antes de dimensionar riesgo, SL BUY sube y SL SELL
baja al grid; TP BUY baja y TP SELL sube. Ambas protecciones se acercan a la
entrada respecto al candidato anterior. Se rechazan protecciones colapsadas o
que incumplen distancia minima. Con `tick_size == point` se conserva la politica
anterior de precios SL/TP.

FillModel compartido aplica slippage y luego redondea contra la posicion:

| Posicion | Entrada | Salida SL/TP o mercado |
|---|---|---|
| BUY | techo del ask + slip | piso del precio de salida - slip |
| SELL | piso del bid - slip | techo del precio de salida + slip |

Una salida TP no recibe mejora artificial por redondeo. Los fills con slippage
fraccional o grid mas grueso pueden tener costes mayores que antes; requieren
volver a generar evidencia historica. El evento usa
`execution_simulation_v2_tick_grid` y conserva slippage nominal ademas de
`metadata.price_grid.effective_slippage_points`. Zero lot solo solicita precio;
los sinks de apertura siguen exigiendo lotaje positivo y presupuesto aprobado.
El modelo comun rechaza lotajes no finitos, negativos, fuera de min/max/step;
datos de precio, tiempo, simbolo o grid invalidos; contexto temporal NaN/futuro;
y resultados de costes no finitos. Replay explicito proporciona edad cero,
mientras PaperFillModel conserva el limite independiente de cinco segundos.

El manager dimensiona nuevamente desde el fill final y reserva la salida SL
que devuelve el mismo modelo con `exit_result(lot=0, base_price=SL)`. Incluye
comision roundturn una vez; nunca aumenta el lote aprobado. La validacion final
del manager rechaza precios de un proveedor externo fuera del grid. Estas
pruebas verifican que el cierre SL modelado no excede el presupuesto; un gap
real o historico puede exceder un stop y no queda garantizado por esa reserva.

Verificacion local, sin terminal MT5 ni datos productivos:

```powershell
py -3.14 -B -m pytest tests/python/test_shared_price_grid.py tests/python/test_paper_fill_risk_reconciliation.py tests/python/test_paper_fill_freshness.py tests/python/test_phase14_execution_simulation.py tests/python/test_shared_decision_core.py tests/python/test_backtest_causality.py tests/python/test_phase82_backtest_live_parity.py
```

Casos: igualdad exacta Paper/Shared en ambas direcciones y multiples grids;
SL/TP conservadores; ticks de cinco puntos con slip de un punto y comision;
presupuesto post-fill y PnL al SL; NaN/Inf/bool/tipos invalidos; cotizacion futura;
lotaje invalido; integridad de la politica legacy cuando point y tick coinciden.
