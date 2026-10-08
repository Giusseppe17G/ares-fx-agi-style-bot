# Conversion determinista de spread a points

Estado: implementado en lectura de mercado, normalizacion de ticks y contrato
del ciclo paper. Areas: datos, ejecucion de lectura y backtesting.

## Problema comprobado

La resta binaria `(ask - bid) / point` producia 4.999999999988347 para una
cotizacion decimal de 5 points. Una cotizacion equivalente con otro precio podia
producir 5.000000000010552. El builder causal compara el spread actual con el
historico; esa diferencia puede transformar un empate de percentil 50 en 0 o
100. Forward y replay podian discrepar con la misma cotizacion declarada.

El adapter tambien aceptaba algunas cotizaciones NaN/Inf/bool o lanzaba una
excepcion de tipo para None antes de producir un rechazo estructurado.

## Decision y compatibilidad

`core.price_grid.spread_points_from_prices` calcula la diferencia con
`Decimal(str(value))` y precision explicita, valida precios ordenados positivos y
point positivo, y rechaza resultados no representables. No redondea a enteros,
tick_size ni umbrales. Fracciones reales, incluido un exceso minimo sobre el
limite, se conservan.

El adapter valida los valores brutos antes de coercion float y devuelve
`MARKET_DATA_INVALID` ante datos invalidos. El payload y MarketSnapshot comparten
el resultado calculado. No se exponen valores brutos invalidos en ese rechazo.
La normalizacion usa el helper cuando deriva el spread; un spread suministrado
se conserva segun el contrato existente. No se cambian limites ni APIs de ordenes.

## Verificacion

Los seis casos iniciales reprodujeron fallos antes del cambio. La suite enfocada
de precision, adapter, indicadores y features compartidas paso 68 pruebas con
Python 3.14 (sin MT5 real). Incluye empate real del builder, fracciones, JPY,
spread cero, limite 25 frente a 25.0001 y datos invalidos/no representables.
Ver `tests/python/test_spread_point_precision.py`.

Esta correccion elimina una divergencia numerica; no acredita que los precios
sean observados, que el reloj sea autentico ni que la estrategia sea rentable.
