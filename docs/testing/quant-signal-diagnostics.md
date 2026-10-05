# Diagnostico causal de senales y contrato de features compartidas

Fecha: 2026-10-05. Modulos: estrategia, datos y verificacion de investigacion.
Base de trabajo: `fe73f7cf1f5631e95b71feb73fc589042b1059f2` mas cambios
revisables de esta rama. Versiones corregidas de las seis estrategias y ensemble:
`0.2.1`. Features: `closed_bar_features_v1`.

## Resultado y limites

Las cero candidatas del replay original no demostraban ausencia de setups:
32.651 barras producian una direccion en el ensemble, pero TODAS perdian el
filtro de componentes por un error en la direccion usada para puntuar calidad.
Corregir solo ese error deja cero candidatas, porque revela otra carencia real:
el adaptador historico no entregaba estructura de mercado. El pipeline completo
con features calculadas y el filtro de calidad restaurado produce 1.227 barras
que pasan CONSERVATIVE en el diagnostico descrito abajo.

Esas barras NO son 1.227 operaciones: el conteo evalua todas las barras despues
del warmup, antes de cooldown, lotaje, risk/execution gates o simulacion de fills.
No se midio ni se afirma edge/rentabilidad con este conteo. No se cambiaron
umbrales, ponderaciones, SL/TP, lotaje, riesgo, permisos o promocion.

Todo el intervalo inspeccionado queda identificado como **datos de diagnostico**,
no como holdout final. Ninguna eleccion se hizo sobre rentabilidad de un test.
Las formulas nuevas son hipotesis explicitas pendientes de validacion OOS con
datos no inspeccionados. La correccion no habilita MT5 ni cuenta real/demo.

## Causas demostradas

1. Las seis estrategias llamaban `strategy_metadata` sin `direction`.
   `_momentum_component` devolvia 40 para cualquier momentum no nulo y 55 para
   momentum cero cuando no habia direccion. CONSERVATIVE exige minimo 60 por
   componente. La direccion ganadora ahora se pasa antes de construir metadata:
   momentum alineado puntua 85 y momentum opuesto sigue puntuando 40.
2. `_features_from_row` historico omitia `trend_structure`/BOS, niveles de
   soporte/resistencia, zscore, compresion/participacion y mechas/sweeps. Sin
   direccion, estructura obtenia 65 neutral; con direccion correcta y datos
   ausentes obtiene 45, que debe bloquear. El arreglo calcula los datos, sin
   sustituir evidencia ausente por puntuaciones favorables.
3. Breakout recibia compresion default=1 y era bloqueado en todas las barras;
   liquidity sweep no recibia precios extremos anteriores ni ratios de mechas y
   tambien era bloqueado en todas las barras. Mean reversion no recibia niveles
   ni zscore y evaluaba defaults degenerados.
4. Ensemble no propagaba `setup_quality_score`. El gate historico trataba cero
   o ausencia como motivo para omitir la comprobacion. Ahora ensemble publica la
   media aritmetica de calidad de TODOS los votantes de la direccion ganadora,
   consistente con la media de componentes preexistente. Si cualquier calidad
   falta, no es finita, es booleana o esta fuera de [0,100], no se inventa el
   campo y se marca `required_data_missing=True`. El principal integra el gate
   que exige calidad presente/finita; confidence no sustituye a calidad.
5. Los builders shadow/probe heredados forzaban `session='LONDON'`. El builder
   comun etiqueta sesion a la hora UTC de decision y excluye barras en curso.

## Contrato del builder puro

Archivo: `src/python/agi_style_forex_bot_mt5/data/strategy_features.py`.

- `closed_strategy_bars(bars, snapshot)` filtra apertura + duracion <= decision.
  Rechaza resultado vacio, timestamps sin zona, duplicados o fuera de orden y
  OHLC/volumen/spread invalidos. Una barra en curso nunca participa.
- `prepare_strategy_features(bars, point=..., max_spread_points=...)` recibe
  barras RAW normalizadas con `timestamp_utc`, OHLC, `volume` y `spread_points`.
  Retorna indicadores, regimen y contexto por fila en forma vectorizada. No
  recibir un frame ya enriquecido. La preparacion no implica disponibilidad.
- `strategy_features_at(frame, idx, snapshot, max_spread_points=...)` extrae una
  fila preparada y exige disponibilidad de candle, punto/simbolo/timeframe
  compatibles y todos los valores numericos criticos finitos. Historia
  insuficiente rechaza. No examina filas posteriores a idx.
- `build_strategy_features(bars, snapshot, max_spread_points=...)` combina filtro
  de candles cerrados, preparacion y extraccion del ultimo candle cerrado; sirve
  para shadow. Backtest prepara una vez y extrae cada idx para evitar O(n^2).

La metadata incluye `feature_version`, `source_bar_timestamp_utc` y
`available_at_utc`. Los bloques `market_structure`, `liquidity`,
`volatility_context`, `price_action` y `session_levels` preservan contexto
auditable; no afirman paridad completa de todos los campos historicos legacy.

## Definiciones fijadas antes del replay integrado

| Feature | Definicion causal |
| --- | --- |
| Indicadores/regimen | Implementaciones existentes EMA20/50/200, RSI14, ATR14, BB20, momentum10, volatilidad20 y reglas de regimen sin cambiar umbrales. |
| support/resistance, prior/prev low/high | Min/max de 20 candles anteriores, excluyendo candle de senal. |
| zscore | `(close - bb_middle) / ((bb_upper - bb_lower)/4)`; varianza cero da cero stretch. |
| compression_ratio | Media de rango high-low de 5 candles anteriores / media de 20 anteriores; excluye candle actual. `range_compression` usa el umbral existente 0,65. |
| volume_ratio | Volumen actual / media de 20 volumenes anteriores. Denominador cero queda indefinido y bloquea. |
| ATR expansion | ATR14 actual / media de 50 ATR14 anteriores. |
| atr_percentile | Rango porcentual promedio del ATR14 actual dentro de sus ultimas 50 observaciones; mide ATR, no rango de una sola vela. |
| spread_percentile | Midrank observado: `100*(n_menores + 0.5*n_iguales)/50`, usando spreads hasta la fila actual y el spread del snapshot como valor consultado. Serie constante da 50. |
| body/wick ratios | Cuerpo/mecha dividido entre high-low; candle de rango cero da cero. |
| expansion_candle | Rango actual > 1,4 * mediana de los 50 rangos anteriores y body_ratio >= 0,5, conservando constantes del contexto existente. |
| follow_through_points | `(close - previous_close)/point`; no usa una vela futura. |
| Sweeps/reclaims | High/low actual cruza extremos previos20; reclaim exige cerrar al otro lado del nivel. |
| Estructura | Pivots con 2 candles a cada lado, publicados solo cuando cierra el segundo candle derecho. Ultimos dos highs/lows confirmados determinan UP/DOWN/RANGE; sin ambos pares queda UNKNOWN. BOS compara close con ultimo pivot confirmado. |
| Sesiones | UTC: Asia00-06, London07-11, overlap12-16, NY17-20, rollover21-23. Usa decision time; no fuerza Londres. |

Las ventanas/constantes anteriores no fueron barridas ni optimizadas. H1 bias no
se fabrica desde M5. Las sesiones UTC fijas son una convencion de investigacion,
no una certificacion de horario DST o timezone del broker. Las series requieren
provenance externa; el builder no verifica procedencia del proveedor.

## Evidencia sobre barras reales disponibles

Fuente local: `data/runs/20260517-232501-real-data-research/historical/`.
20.000 barras M5 por simbolo; se evaluaron indices 220..19.999: 19.780 por simbolo,
59.340 evaluaciones en total. Timestamps tal como estan codificados en los CSV:
EURUSD desde 2026-02-09 13:40Z; GBPUSD y USDJPY desde 2026-02-09 12:10Z; los tres
hasta 2026-05-18 02:25Z. El origen broker/timezone no se recertifico aqui.

| CSV | SHA-256 |
| --- | --- |
| EURUSD_M5.csv | `1243ab89a63d325ced18048437675b9c6ed38e3248beeeb44b92b380991b88ac` |
| GBPUSD_M5.csv | `5f497c028cfc6ce648bfdf6583d7400b981c14326043bdcfdb0961dc879a031f` |
| USDJPY_M5.csv | `1e3ffb936cd35c9cbc5d979848100a77b194e099f9b416c146e25e9c09008c7d` |

| Etapa | EURUSD | GBPUSD | USDJPY |
| --- | ---: | ---: | ---: |
| Direcciones ensemble baseline | 10.818 | 11.034 | 10.799 |
| Pasan perfil baseline | 0 | 0 | 0 |
| Pasan perfil con SOLO arreglo direccion | 0 | 0 | 0 |
| Momentum=85 despues de direccion | 8.801 | 8.993 | 8.792 |
| Momentum opuesto=40 conservado | 1.942 | 1.980 | 1.943 |
| Momentum plano=55 conservado | 75 | 61 | 64 |
| Direcciones con builder+direccion+setup gate | 12.022 | 12.101 | 11.306 |
| Pasan CONSERVATIVE antes de cooldown/fills | 324 | 478 | 425 |
| Errores de features | 0 | 0 | 0 |
| Direcciones breakout ahora observables | 58 | 56 | 79 |
| Direcciones sweep ahora observables | 1.159 | 1.234 | 1.143 |

Bloqueos posteriores al arreglo completo (pueden solaparse en una misma barra):

| Motivo | EURUSD | GBPUSD | USDJPY |
| --- | ---: | ---: | ---: |
| component_score_below_min | 11.469 | 11.337 | 10.619 |
| setup_score_below_min | 3.980 | 3.912 | 3.818 |
| structure_fit_below_min | 4.707 | 4.696 | 4.523 |
| volatility_fit_below_min | 7.725 | 7.661 | 6.862 |
| session_fit_below_min | 3.223 | 3.259 | 3.074 |
| cost_fit_below_min | 76 | 16 | 10 |

Muchos bloqueos persisten por condiciones de mercado o por la incompatibilidad
de un setup con el perfil conservador. No son motivos para bajar filtros.

## Reproduccion de diagnostico integrado

Ejecutar desde la raiz con Python 3.14 y `-B`. Poner la ruta del directorio de
CSV en `HISTORICAL_DIR`; el siguiente codigo no realiza IO de red, MT5 ni ordenes.
Es un conteo de componentes, no un reporte de backtest apto para promocion.

```python
import os, sys
from pathlib import Path
from collections import Counter
from dataclasses import replace
import pandas as pd
sys.path.insert(0, "src/python")
from agi_style_forex_bot_mt5.backtesting import backtester as bt
from agi_style_forex_bot_mt5.config import BotConfig
from agi_style_forex_bot_mt5.data.strategy_features import prepare_strategy_features, strategy_features_at
from agi_style_forex_bot_mt5.strategy.strategy_ensemble import evaluate, EnsembleConfig

cfg = BotConfig()
profile = bt._signal_profile_settings(cfg.signal_profile, cfg.profile_config)
for symbol in ("EURUSD", "GBPUSD", "USDJPY"):
    bars, _ = bt.load_historical_csv(Path(os.environ["HISTORICAL_DIR"]) / (symbol + "_M5.csv"), symbol=symbol, timeframe="M5")
    point = bt.assumed_fx_spec(symbol).point
    frame = prepare_strategy_features(bars.rename(columns={"timestamp": "timestamp_utc"}), point=point)
    actions, failures = Counter(), Counter()
    passes = 0
    for idx in range(220, len(frame)):
        row = frame.iloc[idx]
        snapshot = bt._snapshot_from_row(row, symbol=symbol, timeframe="M5", point=point, config=cfg)
        snapshot = replace(snapshot, timestamp_utc=(row.timestamp_utc + pd.Timedelta(minutes=5)).to_pydatetime())
        features = strategy_features_at(frame, idx, snapshot)
        signal = evaluate(snapshot, features, config=EnsembleConfig(threshold=profile["ensemble_min_score"]))
        actions[signal.action.value] += 1
        if signal.action.value != "NONE":
            passed, reasons = bt._profile_threshold_result(signal.metadata, profile, ensemble_score=signal.score)
            passes += passed
            failures.update(reasons)
    print(symbol, dict(actions), passes, dict(failures))
```

Los fingerprints/commit definitivos y resultados de fills se conservan en el
replay del principal. Este diagnostico usa metadatos broker supuestos, declara
`operationally_eligible=False` conceptualmente y no sustituye Risk Gate.

## Verificacion y pendientes

Pruebas: `test_strategy_directional_scoring.py`,
`test_shared_strategy_features.py`, `test_strategy_engine.py` y
`test_phase16_strategy_quality.py`. Cubren BUY/SELL en las seis estrategias,
momentum adverso, calidad ausente/no finita, gate demo, identidad entre prefix y
batch, perturbacion del futuro/barra en curso, retraso de pivots, niveles previos,
sesion al cerrar candle, inputs invalidos y snapshot no finito. Sin MT5 ni red.

Pendientes operativos: validar costes y metadata del broker, dataset de mayor
cobertura, splits nuevos no inspeccionados, estrategias sin optimizacion oculta,
walk-forward/Monte Carlo segun contrato, y forward auditado. Los resultados
anteriores que utilizaban builders distintos o setup gate omitido necesitan
reevaluacion; no se sobrescribieron sus artefactos.
