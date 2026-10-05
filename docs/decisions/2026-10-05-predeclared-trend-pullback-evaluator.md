# Evaluacion parametrizada y predeclarada de trend pullback

Estado: implementada para investigacion offline; sin promocion ni ejecucion.
Contrato principal: PROJECT_SPEC 17.6 y protocolo previo
`docs/research/trend-pullback-predeclared-v1.md`.

## Decision y compatibilidad

`strategy_trend_pullback.evaluate(snapshot, features, *, params=None)` admite
`TrendPullbackResearchParams` immutable con cinco campos: rsi_buy_min/max,
rsi_sell_min/max y min_score. Se aplican directamente en las condiciones RSI y
en choose_direction. Defaults 38/58/42/62/62 mantienen las salidas y metadata
anteriores; no se cambia STRATEGY_VERSION, ensemble ni features. La nueva ruta
se identifica como `trend_pullback_research_v1`. Esto no hace equivalentes los
resultados anteriores a los actuales: se requiere tambien commit/hash de codigo.

La API de parametros rechaza desconocidos, bool, valores no finitos, limites
fuera de [0,100] e intervalos invertidos. El plan v1 restringe su uso a las tres
hipotesis previamente declaradas 62/70/78 con RSI default, sin seleccionar una.
EMA, SL/TP y costes no son parametros de esta estrategia. Indicadores, pesos,
regimen y protecciones conservan las reglas compartidas.

## Plan, identidad y unidades

`ExperimentPlan` guarda exclusivamente una cadena JSON canonica; las estructuras
que entrega son copias. El parser rechaza campos desconocidos/ausentes,
duplicados JSON, constantes no finitas y protocolos no soportados. `plan_id`
es SHA256 del JSON. Hypothesis_id liga nombre/version/los cinco parametros;
evaluation_id liga plan/hipotesis/simbolo/tramo/versiones de motor y evaluator.

El plan liga datos canonicos OHLCV/spread, filas por tramo, hashes originales,
proveedor/calidad, instrumento, modelo de costes completo, gestion, lote,
capital, semilla, commit y source hash. La normalizacion admite timestamp o
timestamp_utc y volume o tick_volume, pero nunca ambos aliases simultaneamente.
No reordena, deduplica, rellena precios ni infiere timezone. Columnas ajenas al
contrato OHLCV no se usan para senales; el hash del archivo original se conserva
por separado. Un cambio en cualquiera de los datos consumidos invalida la celda.

`denomination_currency` es obligatorio (tres letras ASCII mayusculas). Debe
coincidir con tick_value_currency y commission_currency; no se convierte moneda.
Tick value y costes declaran ASSUMED u OBSERVED. `swap_mode=NOT_MODELED` es la
unica capacidad aceptada. La geometria de CostModel debe coincidir con
InstrumentSpec, sin reemplazo silencioso; el lote fijo debe satisfacer min/max
y lattice min+n*step. La estimacion de fill no impone limites ficticios de lote.

El runner persiste el plan antes de evaluar y verifica source/commit actuales
y archivos originales. El evaluator verifica el hash normalizado y las filas
de su simbolo. Estas responsabilidades se separan para que las pruebas puras
puedan usar provenance sintetica sin consultar Git ni archivos externos.

## Causalidad y particiones

Los cortes UTC comunes 60/20/20 usan duracion temporal, no percentiles de filas
por simbolo. Se materializan desde max(primer timestamp) y min(ultimo cierre),
con aritmetica entera en nanosegundos. Son ventanas [inicio,fin). Solo source
bars que empiezan dentro y estan cerradas pueden participar. Una decision cuya
disponibilidad iguala fin pertenece al siguiente instante y se excluye aqui.

Se preparan hasta 250 barras estrictamente anteriores al inicio. El primer
tramo, si no tiene prehistoria, excluye sus primeras 250 observaciones antes de
evaluar. Ninguna barra de warmup genera trade. El horizonte ex ante requiere que
la barra de entrada y todas las max_holding_bars esten disponibles en el tramo,
incluido el cierre de la ultima. No se pregunta primero si el trade saldria
antes: las decisiones de borde se registran antes de evaluar estrategia/PnL.
Gaps permanecen en timestamps y en la calidad declarada; no se inventan barras.

Por barra se conserva motivo de exclusion, decision NONE o candidato y su
identidad. Backtester conserva rechazos de simulacion y resultados. No se aplica
el cooldown del generador ensemble ni se afirma que el score sea consenso.
La politica de esta ruta es una evaluacion por cada barra elegible.

## Evidencia y limites

Estados de celda: COMPLETED, NO_TRADES, NO_CANDIDATES o INSUFFICIENT_DATA; fallos
son errores que el runner debe registrar. Los resultados conservan capital y
PnL propios de cada tramo. No se reutiliza train como test. Los roles disponibles
son DEVELOPMENT_DIAGNOSTIC_ALREADY_INSPECTED y SYNTHETIC_FIXTURE; final_holdout
siempre NOT_AVAILABLE. Baselines y walk-forward no ejecutados permanecen
NOT_EVALUATED. Seleccion posterior necesita nuevo plan y walk-forward.

La simulacion interpreta OHLC como midpoint, aplica spread de barra de entrada
y lo reutiliza al salir. No representa ticks bid/ask, swap, conversion historica,
cartera, margen ni riesgo agregado. Las metricas son de trades cerrados y de
candidatos independientes con lote fijo; no son retornos de cuenta. Los tres
indicadores full_risk_pipeline_applied/full_pipeline_verified/promotion_eligible
siempre son False. No se modifican gates ni callers operativos.

PnL/trades/equity y metricas no finitas inesperadas producen error. Unicamente
profit_factor positivo infinito, respaldado por trades finitos sin perdidas y
con algun beneficio, se serializa como null con UNBOUNDED_NO_LOSSES. Recovery
sin drawdown monetario conserva el None definido por el motor. No se oculta
overflow convirtiendo resultados monetarios a null.

## Verificacion

Pruebas sinteticas integran indicadores, estrategia, stop builder y Backtester:
trades efectivos en cada tramo; umbral aplicado; prefijos y futuros alterados;
warmup; exclusion de horizonte antes de conocer score/salida; identidad estable;
mutacion de datos bloqueada; historia insuficiente; finitud y overflow. La
revision independiente prueba individualmente los cuatro limites RSI, defaults,
mutabilidad, roundtrip, moneda, coste/instrumento y lote. No se ejecuta el estudio
real ni se seleccionan parametros mediante estas fixtures de software.
