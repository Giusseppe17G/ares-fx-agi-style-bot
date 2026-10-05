# Usar tick_size real en el backtester OHLC

Scope: backtesting y simulacion; sin ruta de ejecucion broker.

La revision del nuevo evaluator encontro que CostModel.tick_size solo afectaba
PnL. El snapshot usado por SharedFillModel inventaba tick_size=point. Con
point=0.00001, tick_size=0.00005 y slippage de un punto, el motor ejecutaba BUY
a 1.10001 desde 1.10000, fuera de la rejilla declarada; correspondia 1.10005.

Engine 0.3.2 transmite tick_size a las dos patas del fill. Ademas rechaza SL/TP
iniciales fuera de rejilla y ajusta stops dinamicos hacia el lado conservador
usando Decimal, sin aflojar protecciones existentes. Los helpers privados
aceptan un keyword opcional para compatibilidad; el motor siempre lo suministra.
Riesgo inicial, excursion y comparacion con triggers se derivan como decimales.
Una reproduccion BUY con riesgo 0.001 y avance 0.0006 no activaba BE=0.6R por
ruido binario; ahora el umbral exacto se respeta en ambas direcciones.

El snapshot REPLAY pide solo precio (lot=0), por lo que sus campos de volumen
son placeholders. La validacion de lote requiere InstrumentSpec en el caller;
no se agrega un limite ficticio de 100 lotes al evaluator. Tampoco se atribuye
gestion de cartera a candidaturas independientes.

Verificacion: 12 regresiones nuevas fallaron antes del cambio y pasaron despues,
incluyendo ambas direcciones, las dos patas y el efecto monetario, protecciones
invalidas, trailing y break-even. Con suites backtesting, causalidad, rejilla
compartida y paridad legacy, mas dos casos de umbral exacto: 224 pruebas pasan.
El caso BUY de umbral exacto tambien fallo antes de corregir la comparacion.
No se ejecutaron ordenes ni se
usaron datos de mercado nuevos en esta verificacion.

Compatibilidad: reportes engine 0.3.1 permanecen historicos. Los que usaron una
rejilla mas gruesa que point o stops dinamicos en umbrales exactos requieren
recalculo. Esta correccion no valida
ambiguedad intrabar, procedencia del broker ni pipeline completo de riesgo.
