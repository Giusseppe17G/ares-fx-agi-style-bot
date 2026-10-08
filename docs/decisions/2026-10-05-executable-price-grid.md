# Grid de precios comun y deslizamiento conservador

Estado: aceptado para simulacion paper y replay. No habilita MT5 ni promocion.

La revision reprodujo una apertura con tick_size 0.00005, point 0.00001,
SL 1.09907 y fill 1.10011: ambos precios tenian cinco decimales pero no eran
ejecutables en el grid del broker. La validacion al final del manager bloquea
proveedores inconsistentes, pero los productores deben generar precios validos.

Decision: una utilidad Decimal pura centraliza alineacion. SL y TP del policy
compartido se alinean hacia entrada antes del calculo de riesgo. Los fills
compartidos se alinean adversamente despues de aplicar slippage; Paper y replay
consumen la misma funcion. El manager reserva su salida SL mediante ese modelo,
incluye comision roundturn y reduce el lote si el coste final supera el
presupuesto previo. Esta reserva no afirma proteccion frente a gaps.

Compatibilidad: firmas publicas existentes no cambian; la utilidad y metadata
son aditivas. `execution_simulation_v2_tick_grid` distingue el cambio de costes.
La politica anterior SL/TP se conserva si tick_size=point. Los fills fraccionales
o con grid grueso pueden empeorar respecto al resultado antiguo y la evidencia
de backtest debe regenerarse. Ante ausencia o incoherencia de metadata, se
rechaza la simulacion; no se adivina un tick a partir de digits.

Pruebas y contrato detallado: `docs/testing/shared-price-grid-validation.md`.
