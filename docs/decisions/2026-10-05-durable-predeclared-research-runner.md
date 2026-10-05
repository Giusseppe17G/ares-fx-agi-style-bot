# Runner durable para la comparación predeclarada

Fecha: 2026-10-05. Alcance: investigación offline y backtesting de candidatos
independientes. Predeclaración: `docs/research/trend-pullback-predeclared-v1.md`.

## Decisión

Se añade `research.predeclared_runner`, separado del runner legacy. Recibe un
`ExperimentPlan` y los frames explícitos; verifica los bindings completos del
plan, commit y hash actual de fuentes. Si existen paths declarados, compara
también bytes del CSV y contenido canónico decodificado con los datos del plan.
Una API que solo entregue frames declara `raw_source_hash_verified=False`;
recibir un hash declarado no demuestra haber leído el archivo correspondiente.

El directorio de salida debe ser nuevo. Antes del primer evaluator se escriben
exclusivamente `plan.json`, `inputs.json` y `manifest.json`, con flush, fsync y
verificación de lectura. El plan se conserva en su forma canónica exacta.
`journal.jsonl` registra el inicio de cada celda antes de evaluarla. Cada celda
identifica plan, hipótesis, símbolo y split; el plan liga estrategia/versiones,
fuentes, parámetros, datos, splits, instrumentos, moneda, lotaje y costes.

Se ejecuta toda la matriz de tres umbrales por símbolo por tres tramos, sin
seleccionar ganador. Cada celda guarda sus propias métricas, decisiones,
rechazos del backtester y trades. Los archivos de evidencia tienen hash. Solo
después de persistir la celda se registra `EVALUATION_COMPLETED`. No se copia
train hacia otra partición.

Un fallo del evaluator produce una celda FAILED y no impide registrar las otras
comparaciones independientes. Un cambio de binding antes/después de evaluar
bloquea las siguientes celdas como NOT_EVALUATED; se revalida el plan en disco
también después de la última evaluación. Un fallo de almacenamiento obligatorio
aborta sin producir un summary de éxito. No hay reintento ni sobrescritura de
artefactos; una ejecución incompleta permanece como evidencia revisable.

## Serialización y compatibilidad

No cambian APIs de forward ni backtester. La nueva CLI separa `plan` y `run`,
exige capital, lotaje, moneda, management, metadata y costes explícitos, y no
descubre datasets o modelos. JSON con claves repetidas, NaN o infinito se rechaza.
Profit factor sin pérdidas conserva `null` más `profit_factor_status` explícito;
no se transforma en un número arbitrario ni en aprobación.

Los frames usan timestamps de apertura con zona horaria y columnas canónicas.
La API cuantitativa es responsable de causalidad, warmup de 250, particiones
60/20/20 y exclusión del horizonte incompleto antes de simular. El runner valida
que el resultado pertenece a la celda solicitada y mantiene los flags cerrados.

## Límites de evidencia

El hash de fuentes es del contenido en disco, no una atestación de módulos ya
importados en un proceso largo. El uso reproducible recomendado es la CLI en
proceso nuevo después de congelar fuentes; editar código durante una corrida
invalida el binding. El directorio tiene un único escritor; hashes detectan
inconsistencias de contenido, no autentican proveedores ni protegen frente a
un actor que sustituya simultáneamente toda la evidencia.

El estudio no es cartera, holdout final, walk-forward, baseline ni evidencia de
rentabilidad validada. `NONE_COMPARE_ALL`, `final_holdout=NOT_AVAILABLE`,
`walk_forward=NOT_EVALUATED`, `baselines=NOT_EVALUATED`,
`full_pipeline_verified=False` y `promotion_eligible=False` permanecen en los
resultados. No se habilita conexión ni ejecución de órdenes.
