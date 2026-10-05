# Hipotesis previa: comparar selectividad de trend pullback

Fecha de declaracion: 2026-10-05. Scope: investigacion offline de desarrollo.
Se escribe antes de implementar el evaluator parametrizado y de ejecutar esta
comparacion. No es un registro externo con sello temporal ni prueba de edge.

## Hipotesis y universo

La continuacion de una tendencia tras un retroceso puede generar candidatos con
distinta calidad segun la selectividad del score existente. Compararemos el
umbral actual 62 frente a 70 y 78, manteniendo las demas condiciones constantes.
No suponemos que un score mas alto tenga mayor probabilidad ni rentabilidad;
la prueba puede dar ausencia de operaciones o resultados negativos.

Universo inicial: EURUSD, GBPUSD y USDJPY, M5. Los datos disponibles de
febrero-mayo 2026 ya fueron inspeccionados y son desarrollo. Una fixture sintetica
sirve para verificar software, nunca para probar rendimiento financiero.

## Reglas y parametros congelados

Se reutiliza `strategy_trend_pullback` version actual, incluyendo el filtro de
regimen/fuerza de tendencia, extension maxima, spread, puntuaciones de EMA,
pendiente, pullback, vela de reanudacion y profundidad respecto a ATR. Features
mantienen EMA20/50/200, RSI14, ATR14 y los demas calculos causales compartidos.
No se cambia la definicion de esos indicadores para mejorar este estudio.

Cinco parametros consumidos: RSI BUY minimo 38/maximo 58, RSI SELL minimo
42/maximo 62 y min_score. Las tres hipotesis usan min_score 62, 70 y 78.
La API valida intervalos finitos/ordenados y score admisible; rechaza claves no
implementadas. Los nombres del grid legacy no constituyen soporte de EMA o SL/TP.

SL/TP usan `build_signal_prices`: distancia maxima entre ATR, 100 points y
dos veces stops_level; TP 1.8 veces esa distancia, con rejilla ejecutable.
Lotaje, capital, comision, spread/slippage y gestion posterior son entradas
explicitas del plan e identicas entre hipotesis. No se seleccionan costes.
Un coste desconocido o supuesto impide conclusion operativa.

Primera corrida de desarrollo: lote fijo 0.1, capital ilustrativo 10.000 USD,
slippage fijo de un point y comision round-turn de 7 USD por lote. Metadata de
`assumed_fx_spec`, incluido valor fijo ilustrativo de 1 USD por tick/lote; no
es una cotizacion de conversion para USDJPY ni metadata verificada del broker.
Spreads originales se conservan, incluido cero, sin imputacion. Gestion:
96 barras maximas, BE 0.6R sin lock, trailing desde 0.8R a distancia 80 points.
Swap y conversion FX no modelados. Estos valores se fijan antes de la corrida;
no se modificaran tras conocer los resultados de las tres hipotesis.

## Protocolo temporal y trazabilidad

Plan canonico persistido antes de evaluar, ligado por hash a codigo, datos,
metadata, costes, reglas de gestion y parametros. Los limites comunes UTC
60/20/20 se materializan a partir de timestamps, no de resultados. Ventanas
[inicio, fin) sin solapamiento; 250 barras anteriores calientan indicadores.
Solo se admiten decisiones disponibles tras cierre dentro del tramo y con todo
el horizonte maximo de salida contenido. Las exclusiones por borde se registran
antes de simular; no se filtran resultados por si ganan o pierden al borde.

Politica de primera entrega: `NONE_COMPARE_ALL`. No se elige una configuracion
ganadora. Los tres tramos conservan metricas propias, todos los intentos y
rechazos. El ultimo se llama development_test; final_holdout=NOT_AVAILABLE.
El posterior uso de sus resultados para seleccionar o cambiar la hipotesis
exigira un plan nuevo, walk-forward y un holdout final nuevo para promocion.

## Invalidacion y limites

Plan/datos/hash diferentes, timestamps ambiguos/duplicados/desordenados, splits
solapados, metadata invalida o claves no soportadas impiden ejecutar el estudio.
Pocos trades, ausencia de trades, costes sin procedencia y resultados negativos
son resultados a conservar, no motivos para reducir filtros o ventanas.

Este estudio usa candidatos independientes y lote fijo, sin gestion de cartera
ni pipeline completo de riesgo, ML y ejecucion. No demuestra paridad forward ni
retornos de una cuenta. Baselines y walk-forward no ejecutados se declaran como
tales. Cero operaciones broker; promocion deshabilitada en todos los resultados.
