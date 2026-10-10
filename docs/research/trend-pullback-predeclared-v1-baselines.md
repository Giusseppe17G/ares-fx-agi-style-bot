# Baselines emparejados del estudio predeclarado trend pullback v1

Fecha: 2026-10-10. Diagnostico de desarrollo sobre datos ya inspeccionados; no
es OOS, no selecciona hipotesis y no habilita promocion ni ejecucion. Metodo:
`docs/decisions/2026-10-10-predeclared-matched-baselines.md`. Evidencia:
`docs/testing/evidence/2026-10-10-predeclared-baselines/`.

## Que se compara

Mismo plan congelado (`6e10245a...`), mismos CSV preservados, mismas barras
elegibles, mismo constructor SL/TP, lote 0.1, costes ilustrativos, gestion y
backtester. Cada barra elegible se simula en BUY y SELL una sola vez; estrategia
y baselines son subconjuntos de esos mismos resultados.

- `direction_flip`: las barras de la estrategia con la direccion contraria.
- `random_entries`: tantas barras aleatorias como trades cerrados de la
  estrategia, direccion aleatoria.
- `random_direction_same_bars`: las barras de la estrategia, direccion aleatoria.
- `trend_direction_random_bars`: barras aleatorias en la direccion EMA20/EMA50,
  sin filtro de pullback ni score.

1.000 replicas por baseline y celda con semilla derivada del plan. "Cuota" es la
fraccion de replicas con PnL >= estrategia, `(k+1)/(R+1)`: cerca de 0 la
estrategia supera al baseline; cerca de 1 el baseline la iguala o supera.

## Reproducibilidad

Las 27 celdas de la estrategia recalculadas con el codigo actual coinciden
exactamente con el estudio preservado (`predeclared-3e9b4d4`): PnL neto, PF,
win rate y drawdown de cierres. Cero discrepancias.

## Resultados (PnL en USD supuestos)

| Simbolo | Tramo | Umbral | Trades | Estrategia | PF | Flip | Aleatorio p50 | Cuota | Misma barra p50 | Cuota | Tendencia p50 | Cuota |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| EURUSD | train | 62 | 6336 | -6977.3 | 0.750 | -4306.9 | -6189.7 | 0.838 | -5618.4 | 0.974 | -9580.0 | 0.001 |
| EURUSD | train | 70 | 4974 | -4926.6 | 0.771 | -4091.5 | -4892.2 | 0.520 | -4529.3 | 0.753 | -7509.7 | 0.001 |
| EURUSD | train | 78 | 2165 | -2189.7 | 0.766 | -670.6 | -2126.3 | 0.548 | -1410.4 | 0.973 | -3302.3 | 0.002 |
| EURUSD | validation | 62 | 2162 | -3877.2 | 0.591 | -1981.5 | -2531.2 | 0.999 | -2929.1 | 1.000 | -2324.5 | 1.000 |
| EURUSD | validation | 70 | 1760 | -2914.6 | 0.611 | -1751.8 | -2067.8 | 0.992 | -2323.5 | 0.970 | -1880.2 | 1.000 |
| EURUSD | validation | 78 | 819 | -1606.7 | 0.565 | -473.8 | -964.8 | 0.995 | -1024.9 | 0.995 | -881.3 | 1.000 |
| EURUSD | development_test | 62 | 2317 | -1983.8 | 0.798 | -2391.3 | -2366.4 | 0.198 | -2195.3 | 0.336 | -1584.9 | 0.928 |
| EURUSD | development_test | 70 | 1889 | -1263.4 | 0.839 | -2397.2 | -1905.6 | 0.048 | -1810.9 | 0.061 | -1259.1 | 0.507 |
| EURUSD | development_test | 78 | 882 | 26.6 | 1.007 | -2070.8 | -904.0 | 0.001 | -1020.4 | 0.001 | -600.2 | 0.007 |
| GBPUSD | train | 62 | 6458 | -6695.9 | 0.773 | -5729.7 | -6064.5 | 0.803 | -6260.5 | 0.731 | -7027.3 | 0.270 |
| GBPUSD | train | 70 | 5124 | -4894.8 | 0.790 | -4953.3 | -4844.7 | 0.528 | -4910.6 | 0.492 | -5527.4 | 0.112 |
| GBPUSD | train | 78 | 2244 | -1904.6 | 0.807 | -2280.3 | -2125.4 | 0.325 | -2119.0 | 0.309 | -2452.7 | 0.106 |
| GBPUSD | validation | 62 | 2124 | -3559.5 | 0.637 | -2032.8 | -2806.7 | 0.965 | -2801.4 | 0.969 | -3323.8 | 0.797 |
| GBPUSD | validation | 70 | 1730 | -2799.3 | 0.644 | -2030.1 | -2293.2 | 0.911 | -2413.7 | 0.845 | -2721.2 | 0.619 |
| GBPUSD | validation | 78 | 750 | -1498.4 | 0.594 | -588.3 | -998.1 | 0.974 | -1036.8 | 0.971 | -1171.3 | 0.919 |
| GBPUSD | development_test | 62 | 2149 | -1539.6 | 0.832 | -3466.0 | -2664.6 | 0.005 | -2508.8 | 0.006 | -776.4 | 0.997 |
| GBPUSD | development_test | 70 | 1761 | -989.4 | 0.866 | -3370.9 | -2168.9 | 0.002 | -2194.4 | 0.001 | -626.9 | 0.893 |
| GBPUSD | development_test | 78 | 798 | 56.2 | 1.019 | -2012.2 | -971.5 | 0.001 | -995.1 | 0.001 | -300.8 | 0.076 |
| USDJPY | train | 62 | 6196 | -8594.8 | 0.697 | -3300.4 | -5507.8 | 1.000 | -5906.4 | 1.000 | -10307.3 | 0.002 |
| USDJPY | train | 70 | 4902 | -6066.3 | 0.724 | -3341.9 | -4369.1 | 0.998 | -4763.5 | 0.990 | -8108.0 | 0.001 |
| USDJPY | train | 78 | 2198 | -4088.5 | 0.622 | -212.1 | -1985.0 | 1.000 | -2138.6 | 1.000 | -3641.3 | 0.865 |
| USDJPY | validation | 62 | 1994 | -3138.9 | 0.663 | -821.1 | -1716.8 | 1.000 | -1952.4 | 0.998 | -3563.5 | 0.077 |
| USDJPY | validation | 70 | 1613 | -2537.0 | 0.665 | -551.0 | -1373.4 | 1.000 | -1573.9 | 0.998 | -2881.8 | 0.130 |
| USDJPY | validation | 78 | 726 | -1589.4 | 0.574 | 44.9 | -627.2 | 1.000 | -763.0 | 1.000 | -1291.7 | 0.888 |
| USDJPY | development_test | 62 | 2212 | -3177.3 | 0.686 | -2411.9 | -2219.4 | 0.986 | -2817.8 | 0.797 | -4097.9 | 0.002 |
| USDJPY | development_test | 70 | 1853 | -2715.2 | 0.678 | -2278.9 | -1860.6 | 0.975 | -2477.1 | 0.709 | -3451.1 | 0.005 |
| USDJPY | development_test | 78 | 864 | -1296.2 | 0.666 | -1023.0 | -868.5 | 0.933 | -1150.5 | 0.716 | -1603.9 | 0.136 |

## Lectura

- Con estos costes, entrar al azar pierde en todas las celdas: el PnL mediano
  de cada baseline aleatorio es negativo en las 27. Un sistema sin ventaja
  pierde aproximadamente el coste de transaccion.
- En train y validation (18 celdas) la estrategia es igual o peor que entrar al
  azar en casi todas: la cuota de `random_entries` supera 0,5 en 17 de 18, y en
  USDJPY y EURUSD-validation el azar la iguala o supera en >97% de las replicas.
- Invertir la direccion de la estrategia mejora el resultado en 19 de 27
  celdas. La seleccion de direccion no aporta informacion favorable en estos
  datos; en varias celdas es desfavorable.
- Solo en development_test EURUSD y GBPUSD superan claramente a los baselines
  aleatorios (cuotas 0,001-0,2), y los dos unicos PnL positivos (umbral 78) son
  marginales. Ese tramo ya estaba inspeccionado, contradice a los anteriores y
  hay 27 celdas por 3 baselines sin correccion por comparaciones multiples: no
  es evidencia de ventaja.
- Frente a la tendencia EMA20/EMA50 sin filtro de pullback el resultado es
  mixto (la estrategia supera la mediana en 15 de 27 celdas): el filtro de
  pullback no muestra una mejora consistente.

Conclusion: en los datos de desarrollo disponibles no hay evidencia de que las
reglas de seleccion de trend pullback superen a entradas aleatorias con
ejecucion y costes identicos. Se mantiene `promotion_eligible=false`. No se
ajustan reglas ni umbrales con estos datos: segun
`docs/testing/next-evidence-protocol.md`, cualquier hipotesis nueva debe
declararse antes y evaluarse sobre datos no inspeccionados con costes del
broker verificados.
