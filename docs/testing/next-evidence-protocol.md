# Protocolo para la siguiente evidencia cuantitativa

Estado: pendiente de broker/cuenta demo y datos verificables. Este documento
define el orden de trabajo; no registra un experimento ejecutado ni reserva
como holdout un periodo que ya se haya inspeccionado.

## Punto de partida congelado

Los CSV M5 EURUSD/GBPUSD/USDJPY de febrero-mayo de 2026 y todos los resultados
observados se clasifican como desarrollo. Las correcciones de software no los
convierten en prueba final. La estrategia ensemble actual pierde bajo costes
ilustrativos; no se promociona ni se reducen sus umbrales para forzar actividad.
Los porcentajes de acierto no sustituyen beneficio neto, riesgo y costes.

## Evidencia necesaria antes de otra conclusion operativa

1. Identificar broker y tipo de cuenta demo, moneda y mapa de simbolos. Capturar
   condiciones del instrumento por la via de lectura y conservar fuente,
   vigencia y hashes. No almacenar identificadores personales ni credenciales.
2. Obtener bid/ask con timestamps, barras cerradas, historial de cambios de
   metadata y especificacion de comisiones/swap. Documentar UTC/DST, huecos y
   cobertura. No convertir OHLC en ticks supuestamente observados. Aclarar los
   spreads cero; conservar lo desconocido como desconocido.
3. Antes de evaluar resultados nuevos, guardar manifiesto de los archivos y
   particiones train/validation/final-test, codigo, configuracion, costes,
   semillas, familias de estrategia y numero maximo de pruebas. Excluir de
   final-test todo tramo ya inspeccionado o usado para elegir una variante.
4. Usar el replay estatal para comprobar estado y costes del mismo camino
   forward. Conservar restricciones conocidas: ranking secuencial, referencia
   diaria overnight exacta y trayectorias entre quotes no observadas. Una
   limitacion que impida verificar el experimento no se sustituye por un pase.

## Comparacion y decision

- Comparar con no-trade, baseline direccional cuando sea pertinente, entradas
  aleatorias con riesgo/frecuencia/costes equivalentes y ablacion del filtro
  principal. Usar identicos datos evaluables y el mismo modelo de ejecucion.
  Implementado en `scripts/run_predeclared_baselines.py` (§17.14); sobre los
  datos de desarrollo actuales la estrategia no supera a esos baselines
  (`docs/research/trend-pullback-predeclared-v1-baselines.md`).
- Registrar todas las configuraciones y rechazos, no solo el ganador. Si se
  seleccionan parametros, usar validacion y walk-forward con purga y tests
  disjuntos. Final-test se abre una vez; cualquier ajuste posterior lo consume
  y exige un nuevo holdout. Separar investigacion sin ML de evaluacion con un
  bundle cuya disponibilidad historica este demostrada.
- Mantener el Strategy Promotion Gate de PROJECT_SPEC 12.1: muestra suficiente,
  PF OOS >1,15 y expected payoff positivo despues de costes, drawdown dentro del
  limite declarado, robustez por periodo/regimen/simbolo, stress y forward
  auditado. Monte Carlo y sensibilidad usan semillas/supuestos registrados;
  los costes no se optimizan para favorecer el resultado.
- Los resultados favorables solo permiten la siguiente revision. La release
  actual carece de capacidad broker y el consolidado observacional no verifica
  por si mismo autenticidad, consistencia entre corridas ni promocion.

Este protocolo aplica los patrones de causalidad, componentes compartidos y
pruebas de sesgo documentados en `docs/EXTERNAL_TRADING_BENCHMARK_2026-10-05.md`.
No atribuye una estrategia rentable a esos proyectos ni copia codigo privado.
