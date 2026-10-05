# Comparacion predeclarada de desarrollo: trend pullback v1

Las 27 celdas terminaron, sin elegir una configuracion ganadora. Las nueve
celdas de validation son negativas, al igual que las nueve de train. En
el tramo development_test hay siete resultados negativos y dos apenas
positivos; ninguno de los 27 profit factors supera 1.15. Esto no demuestra
una ventaja estadistica ni permite promocion.

Son candidatos de una estrategia individual, potencialmente solapados,
evaluados cada barra elegible con lote fijo 0.1. Su conteo no representa
muestras independientes y el PnL sumado no representa una cuenta con limites
de posiciones/riesgo. Se conserva full_risk_pipeline_applied=false y
full_pipeline_verified=false. Los resultados no son comparables directamente
con las 644 candidaturas del ensemble anterior: cambian estrategia, frecuencia,
lote, particiones y version del motor.

Auditoria independiente: 179892 decisiones, 69033 candidatos, 33 rechazos de
spread y 69000 registros cerrados en toda la matriz. Identidades, 54 hashes de
JSONL, 56 eventos de journal y PnL/PF/win rate/expectancy/R/drawdowns recalculados
coinciden. Los picos de candidatos solapados van de 26 a 88 por celda: esta
simulacion NO acredita los limites de una cartera operativa de diez posiciones.

## Identidad y protocolo

- Codigo limpio: 3e9b4d4a7bd2e7d57684669892a68570def676ca; motor 0.3.2.
- Fuentes: 7d47cce2feb761f3d1b10c80c1a493abf5ec633232d442e369e2d83d00703366.
- Plan: 6e10245a0ce90d3d044d3aebd60587c1a4c5e87f6485015279ae2b87878f4611.
- Resultado: d1af27e52606c43d56f03ccad8615aeafba4af3ee52223fa2ea47b2a7a3b14ab.
- Tres umbrales 62/70/78, RSI 38/58 BUY y 42/62 SELL. NONE_COMPARE_ALL.
- Instrumentos, gestion, costes y lote iguales para todas las hipotesis.
- Capital ilustrativo 10000 USD; tick value ilustrativo fijo 1 USD/tick/lote;
  comision round-turn 7 USD/lote y slippage 1 point. No conversion FX ni swap.
- Warmup 250 barras; horizonte completo de 96 barras, comprobado antes del
  resultado. BE 0.6R, trailing desde 0.8R a distancia 80 points.

Ventanas UTC comunes, sin solapamiento:

| Tramo | Inicio incluido | Fin excluido |
| --- | --- | --- |
| train | 2026-02-09T13:40:00+00:00 | 2026-04-09T02:10:00+00:00 |
| validation | 2026-04-09T02:10:00+00:00 | 2026-04-28T14:20:00+00:00 |
| development_test | 2026-04-28T14:20:00+00:00 | 2026-05-18T02:30:00+00:00 |

## Todas las comparaciones

PnL en USD **supuestos**, sin operacion de dinero. Win rate es descriptivo del
historico inspeccionado, no probabilidad futura de acierto. DD corresponde a la
curva de cierres de candidatos independientes, no al patrimonio flotante del bot.

| Umbral | Simbolo | Tramo | Candidatos cerrados | PnL neto | PF | Win rate % | DD cierres % |
| ---: | --- | --- | ---: | ---: | ---: | ---: | ---: |
| 62 | EURUSD | train | 6336 | -6977.30 | 0.7504 | 41.86 | -72.46 |
| 62 | EURUSD | validation | 2162 | -3877.20 | 0.5913 | 38.58 | -41.48 |
| 62 | EURUSD | development_test | 2317 | -1983.80 | 0.7978 | 41.48 | -38.38 |
| 62 | GBPUSD | train | 6458 | -6695.90 | 0.7733 | 40.79 | -68.65 |
| 62 | GBPUSD | validation | 2124 | -3559.50 | 0.6366 | 42.00 | -36.33 |
| 62 | GBPUSD | development_test | 2149 | -1539.60 | 0.8321 | 44.11 | -25.50 |
| 62 | USDJPY | train | 6196 | -8594.80 | 0.6972 | 40.99 | -86.94 |
| 62 | USDJPY | validation | 1994 | -3138.90 | 0.6633 | 40.52 | -35.28 |
| 62 | USDJPY | development_test | 2212 | -3177.30 | 0.6860 | 40.87 | -43.41 |
| 70 | EURUSD | train | 4974 | -4926.60 | 0.7710 | 42.66 | -51.36 |
| 70 | EURUSD | validation | 1760 | -2914.60 | 0.6109 | 39.77 | -30.90 |
| 70 | EURUSD | development_test | 1889 | -1263.40 | 0.8394 | 42.46 | -28.68 |
| 70 | GBPUSD | train | 5124 | -4894.80 | 0.7903 | 41.08 | -50.46 |
| 70 | GBPUSD | validation | 1730 | -2799.30 | 0.6439 | 43.29 | -30.17 |
| 70 | GBPUSD | development_test | 1761 | -989.40 | 0.8657 | 44.63 | -18.29 |
| 70 | USDJPY | train | 4902 | -6066.30 | 0.7241 | 41.19 | -61.45 |
| 70 | USDJPY | validation | 1613 | -2537.00 | 0.6648 | 40.42 | -28.55 |
| 70 | USDJPY | development_test | 1853 | -2715.20 | 0.6778 | 40.58 | -37.42 |
| 78 | EURUSD | train | 2165 | -2189.70 | 0.7657 | 42.26 | -24.69 |
| 78 | EURUSD | validation | 819 | -1606.70 | 0.5651 | 38.34 | -17.18 |
| 78 | EURUSD | development_test | 882 | 26.60 | 1.0074 | 46.94 | -13.75 |
| 78 | GBPUSD | train | 2244 | -1904.60 | 0.8066 | 41.27 | -24.79 |
| 78 | GBPUSD | validation | 750 | -1498.40 | 0.5942 | 41.33 | -18.64 |
| 78 | GBPUSD | development_test | 798 | 56.20 | 1.0188 | 46.74 | -7.05 |
| 78 | USDJPY | train | 2198 | -4088.50 | 0.6224 | 38.35 | -41.65 |
| 78 | USDJPY | validation | 726 | -1589.40 | 0.5738 | 38.02 | -20.36 |
| 78 | USDJPY | development_test | 864 | -1296.20 | 0.6664 | 39.47 | -17.80 |

## Limites y reproduccion

Los tres CSV de 20000 filas se conservaron sin reordenar, rellenar ni descartar
filas. EURUSD tiene 94.225% de spreads cero, GBPUSD 0.04% y USDJPY 86.14%; su
interpretacion no esta resuelta. Origen y costes no estan autenticados. OHLC se
interpreta como midpoint, y el spread de entrada se reutiliza al salir.
USDJPY no usa una conversion historica USD verificada. No se aplican limites
agregados de riesgo, margen o numero de posiciones a estos candidatos.

El historial febrero-mayo 2026 ya estaba inspeccionado. final_holdout permanece
NOT_AVAILABLE, y walk_forward y baselines siguen NOT_EVALUATED. No se cambiaran
los parametros de este plan para borrar resultados negativos. Cualquier nueva
hipotesis requiere otro protocolo; este periodo tampoco podra convertirse en
holdout final. El software permanece sin capacidad de enviar ordenes.

complete-evidence.zip conserva 750 miembros: originales, CSV canonicos, JSON de
entrada, plan congelado, plan/inputs/manifest del runner, 27 celdas, 27 archivos
de decisiones, 27 archivos de trades, journal, summary y 656 archivos de fuentes
exactos usados en la corrida. archive-manifest.json
contiene SHA256 de cada miembro y del ZIP; todos se releyeron y verificaron.
Los archivos de resumen aqui copiados son identicos a los del archivo completo.
Los paths absolutos dentro de la evidencia apuntan a la ejecucion original en
Temp; no son una dependencia de la reproduccion.

Para reproducir, usar un checkout del commit indicado, extraer en una carpeta
nueva y restaurar los bytes de source_snapshot/src y source_snapshot/scripts
dentro de ese checkout. Esto conserva finales de linea y el hash exacto de
fuentes; no altera el contenido logico del commit. Despues ejecutar desde
cualquier CWD con rutas absolutas:

```powershell
py -3.14 -B <checkout>/scripts/run_predeclared_research.py --source-root <checkout> run --inputs <extraido>/inputs/inputs.json --plan <extraido>/frozen-plan.json --output <salida-nueva>
```

El runtime fuente es un hash de archivos, no una atestacion de modulos cargados;
se usaron procesos nuevos. Puede ser necesario conservar exactamente los finales
de linea de las fuentes para reproducir su hash de bytes; un checkout cuyo hash
no coincida se rechaza. El manifest registra Python y dependencias. Recalcular
identificadores con otras fuentes constituye otra corrida, no esta reproduccion.
