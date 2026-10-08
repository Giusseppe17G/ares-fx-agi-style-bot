# Nucleo comun, causalidad y contabilidad paper verificable

Estado: aceptado para investigacion y paper; promocion bloqueada.

La revision multiagente encontro defectos medibles: scoring sin direccion,
features historicas ausentes, calidad de ensemble no propagada, umbrales solo
auditados en forward, referencia diaria reiniciada desde balance broker, libro
de riesgo vacio, ML_ERROR permitido, lot escalado sin respetar step y PnL con
posible segunda escala. La comparacion antigua llamaba dos veces componentes
comunes y no demostraba paridad de las aplicaciones.

Se mantiene el codigo de riesgo/ML/portfolio existente detras de un unico
orquestador determinista con contexto explicito. El caller aporta observaciones,
estado y persistencia; los datos faltantes son bloqueos visibles. Forward usa
este nucleo; replay de decisiones registradas verifica el mismo camino. El
backtest OHLC anterior conserva alcance de candidatos independientes hasta que
se implemente un simulador cronologico de portfolio con ejecucion y costos
equivalentes. No se etiqueta este estado como PARITY_OK global.

Se usa un builder causal comun y la politica de perfil real, sin bajar
thresholds ni optimizar con los resultados ya vistos. Las definiciones nuevas
de features estan en `docs/testing/quant-signal-diagnostics.md`. La correccion
reactiva senales, pero el replay diagnostico con costes produjo perdidas en los
tres pares. Es evidencia contra la promocion, no un motivo para ocultar costes.

El libro paper nuevo usa capital inicial persistido, PnL de lot aprobado una
sola vez, referencias diarias UTC y todas las posiciones marcadas. La evidencia
legacy permanece recuperable; no se migra automaticamente una contabilidad
ambigua. El contrato nuevo de version y marcador esta en PROJECT_SPEC seccion17.
Se preservan riesgo/distancia iniciales tras mover SL para no perder gestion BE.

Metadata observada se congela con hashes y escritura exclusiva. Un hash no
autentica al broker; un snapshot de hoy no verifica costes o tick value pasados.
Manifest1.1 identifica tambien fuentes sin commit. La redaccion mantiene IDs y
secretos ocultos, con excepciones tipadas solo para importes de riesgo, checks
numericos y hashes de perfil necesarios para reproducir decisiones.

Compatibilidad: dataclasses y APIs reciben campos/argumentos aditivos; el nuevo
camino es mas estricto ante entradas antes toleradas. NoML requiere opcion paper
explicita. Walk-forward rechaza ventanas test solapadas y separa calentamiento,
purga y evaluacion; la grilla ya no puede optimizar supuestos de costes.

Pendientes antes de promocion: simulacion cronologica completa, paridad de
transiciones/ejecucion/exposicion y costos, evidencia broker real fechada,
evaluacion en datos nuevos, WFA/Monte Carlo/baselines con muestra suficiente,
modelo causal aprobado si se usa ML, forward representativo y compilacion/pruebas
MT5 requeridas por el gate. DEMO_ONLY=True y LIVE_TRADING_APPROVED=False.
