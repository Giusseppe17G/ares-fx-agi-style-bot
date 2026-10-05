# Replay de cartera con cotizaciones explicitas

Estado: contrato aceptado para investigacion; no promocion de estrategia.

El motor anterior simula candidatos independientes. Aunque comparte features,
umbrales y fills, no transmite entre candidatos el patrimonio, posiciones y
rechazos de los seis controles de decision del forward. El replay de contextos
registrados verifica decisiones aisladas pero no resuelve ese problema.

Se agrega un adaptador de eventos que crea un libro paper nuevo y deriva todo
el estado de sus propias transiciones. Reutiliza `ForwardShadowBot`, el nucleo
comun, ledger, manager y simulador de fills. No copia implementaciones de riesgo,
no conecta al terminal y no descubre automaticamente modelos locales. La
secuencia de candidatos dentro de un evento es explicita y secuencial; no se
presenta como ranking top-N de una cartera completa.

Se eligen cotizaciones bid/ask explicitas. Una barra no determina el orden de
los extremos ni el spread intrabar; fabricar ese camino podria alterar stops,
drawdown, BE y trailing. La alternativa de simular caminos OHLC queda fuera de
este contrato y requeriria escenarios separados etiquetados como supuestos.
La eleccion se apoya en la documentacion primaria de
[NautilusTrader](https://nautilustrader.io/docs/latest/concepts/backtesting/data-and-venues/).

Un evento incompleto puede detener el replay; eso limita la cobertura pero
evita presentar un estado desconocido como seguro. Las referencias diarias
overnight se fijan con cotizaciones exactas de medianoche UTC y no se reescriben.
El sistema preserva inputs, metadata, configuracion/modelo, fuentes y auditoria
para repetir la corrida. Hashes aportan integridad; no prueban origen del broker.

Compatibilidad: nuevo API y script aditivos. Forward acepta modelos y snapshots
inyectados para usar la misma logica en el replay; sus defaults siguen disponibles.
`MLFilter.disabled_for_research()` evita cargar artefactos por accidente y no
elimina el gate explicito de investigacion sin ML. Los reportes legacy conservan
su alcance incompleto; esta nueva ruta no los transforma en validacion integral.

Verificacion: tests de motor, revision independiente, transporte JSONL estricto
y proceso CLI desde otra carpeta. Las fixtures sinteticas prueban coherencia del
software. Quedan pendientes capturas historicas con evidencia broker adecuada,
costes completos, evaluacion OOS y forward representativo antes de promocion.
