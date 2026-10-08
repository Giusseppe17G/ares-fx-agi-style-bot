# Ciclo económico paper compartido

Fecha: 2026-10-05. Áreas: riesgo paper, observabilidad y backtesting.
No autoriza ejecución demo/real ni promoción de estrategia.

## Problema reproducido

Compartir `SharedDecisionPipeline` no hacía equivalentes a los callers. En HEAD
`5e30de0`, el test del bucle forward real con barras sintéticas y evidencia broker
de un día anterior abrió una operación paper; el replay del mismo episodio la
rechazó con `BROKER_EVIDENCE_TIME_INVALID`. Las pruebas de revisión también
reprodujeron continuación al segundo símbolo después de una auditoría fallida,
cuenta/conexión no revalidadas y modificación parcial de posiciones cuando
faltaba la cotización de otra posición.

## Decisión

`paper_trading.lifecycle.process_paper_cycle(bot, PaperCycleInput)` posee la
gestión económica. `ForwardShadowBot.run` adquiere cuenta, conexión, cotizaciones
y barras y llama al método público `process_paper_cycle`. El replay conserva su
manifest, scheduler y validación de metadata congelada, y llama al mismo método.
La apertura, decoración, gestión de stops/cierres, valoración, límites y pausa
diaria ya no tienen implementaciones distintas en los dos bucles.

El input contiene identidad y tiempo del ciclo, `PaperAccountObservation`, todas
las cotizaciones, candidatos ordenados y `PaperEvidence`. Esta última exige
`observed_at_utc`; no se toma la hora actual como sustituto. La conexión debe ser
`True` y la cuenta demo conocida, con capital finito, permiso explícito y moneda
de tres letras ASCII. Login y moneda se comparan en memoria entre ciclos sin
emitir los identificadores. El contrato de cuenta no incluye servidor; esa
comparación no autentica una identidad de broker global.

Antes de modificar el libro se validan todas las cotizaciones y metadata finita.
Se vuelven a comprobar frescura y estado observado antes de candidatos/fills
contra el reloj inyectado actual. El forward no congela el reloj para mantener
vigente una observación. Cuando se entregan snapshots, el ledger nunca completa
una ausencia consultando el terminal.

`PaperCycleResult` conserva decisiones, rechazos, valoración, operaciones sin
UUID de almacenamiento, contadores, pausa, halt y completitud de auditoría. Una
operación efectivamente persistida sigue visible si falla una auditoría
posterior, y las aprobaciones del ciclo incompleto se revocan. Se conserva el
código previo `REPLAY_EVENT_ABORTED` también en ese resultado del forward por
compatibilidad con consumidores existentes.

## Recuperación y pausas

La intención `paper_cycle_in_progress` se persiste antes de las mutaciones y
solo se limpia después de auditar el ciclo completo. Un error enclava el
proceso y el estado persistido. Así, una caída entre fill y auditoría no permite
continuar por un reinicio. Un halt registra primero `paper_audit_complete=False`
y solo confirma `True` después de persistir su auditoría si no había ya una
incertidumbre anterior. Auditar el rechazo del reinicio no sanea el fallo previo.
Se necesita reconciliación explícita; no se añadió un mecanismo de desbloqueo.

El latch diario del ledger determina la pausa económica. Una pausa propia por
drawdown solo expira en un día UTC nuevo con ledger/referencia válidos y
`manual_resume_required=False`. Nunca reemplaza ni limpia una pausa ajena.
La referencia overnight mantiene el contrato de cotizaciones completas en el
instante exacto de medianoche. No se infiere el patrimonio de un instante sin
observaciones.

## Compatibilidad y límites

- Los nombres y el transporte de replay anteriores permanecen; `ReplayEvidence`
  comparte ahora el tipo de evidencia del lifecycle.
- La adquisición conserva el builder causal existente. `PaperCandidate.features`
  admite un resultado ya construido por ese adaptador; no autentica features
  arbitrarias suministradas por un tercero.
- Los proveedores anteriores sin fecha explícita quedan bloqueados. Un fallo
  de valoración ya no produce un ciclo exitoso con métricas desconocidas.
- `ForwardShadowSummary` añade `audit_complete`, `lifecycle_halted` y
  `paper_state_available`. `open_trades=None` expresa almacenamiento ilegible;
  no presenta un libro desconocido como vacío.
- Heartbeats, reportes y transporte de notificaciones siguen siendo del caller.
  Los episodios controlados verifican economía paper y fallos concretos, no
  equivalencia integral de broker, disponibilidad de servicios o reinicios
  arbitrarios de una cuenta real.
- `full_pipeline_verified=False` y todos los bloqueos de ejecución permanecen.

Verificación: [episodios controlados](../testing/forward-replay-lifecycle.md).
