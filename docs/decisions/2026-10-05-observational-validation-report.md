# Consolidacion fail-closed de informes observacionales

Estado: aceptado. Alcance: reporting de backtesting; sin cambios de estrategia,
umbrales, riesgo de ejecucion ni conectividad MT5.

La consolidacion anterior aprobaba cinco secciones ausentes: broker_quality,
readiness, forward_shadow, execution_simulation y paper_vs_backtest. Ademas
propagaba cualquier texto de clasificacion de Monte Carlo, walk-forward y stress;
un texto desconocido no coincidia con REJECTED/WATCHLIST y podia terminar como
aprobacion. El parser aceptaba claves duplicadas y numeros JSON no finitos.
En backtest, la cadena Infinity se sustituia por 999 y drawdown cero por 100.

Decision: report_version 2.0 conserva la firma publica y archivos JSON/CSV/HTML,
pero reconoce exclusivamente etiquetas especificas de cada productor. Una fuente
ausente, vacia, ilegible, mal formada o desconocida no aporta aprobacion. El
informe expone evidence_quality con status, reason, classification normalizada,
source_classification reconocida y path. Las listas missing_sections,
invalid_sections y unknown_classification_sections permiten al consumidor
identificar el hueco sin interpretar texto libre. Un fallo explicito conocido de
broker o estrategia puede conservar prioridad sobre faltantes; todos los motivos
siguen registrados.

Los umbrales numericos de backtest se mantienen: 300 trades, PF>1.25,
expectancy_r>0 y abs(DD)<12 para observacion; PF>1 y expectancy_r>=0 para
watchlist. Los cuatro campos deben estar presentes y ser numeros finitos;
total_trades es entero no negativo. No se convierten strings/bools a numeros.
DD=0 es valido. Infinity no es evidencia numerica suficiente para esa
clasificacion y no recibe un valor sustituto.

La lectura JSON rechaza claves duplicadas en cualquier profundidad, constantes
NaN/Infinity y desbordamientos numericos como 1e400. Los informes de seccion
requieren objetos. Hay dos excepciones reales y documentadas: los productores
research_report/CandidateRegistry escriben listas en recommended_strategy_mix y
candidate_registry. Se conservan listas no vacias de objetos con symbol o
candidate_id respectivamente; su clasificacion es INFORMATIONAL, nunca aprobada
por mera presencia. Forward conserva su caracter de WATCHLIST observacional y
requiere contadores de trades coherentes y no vacios del productor paper_report.

Este modulo consolida etiquetas declaradas; no autentica artefactos ni verifica
la correspondencia entre commits, datasets, ejecuciones, broker o ventanas OOS.
No reconstruye ni certifica todos los calculos de cada productor. Incluso cuando
sus inputs estan disponibles, fija scope=OBSERVATIONAL_REPORT_CONSOLIDATION,
execution_enabled=False, full_pipeline_verified=False y
promotion_authorized=False. El Strategy Promotion Gate es una obligacion
distinta y la release mantiene bloqueada la capacidad de envio MT5.

Compatibilidad: firmas y nombres de artefactos intactos, campos de calidad
aditivos, cambio semantico intencional ante evidencia incompleta. El test legacy
de integracion que aprobaba con cinco fuentes ausentes ahora exige
NEEDS_MORE_DATA y conserva la comprobacion de los tres artefactos producidos.
No se modifican los productores ni PROJECT_SPEC desde este modulo.

Verificacion y limites: `docs/testing/validation-report-fail-closed.md`.
