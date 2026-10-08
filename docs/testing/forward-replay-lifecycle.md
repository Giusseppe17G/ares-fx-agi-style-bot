# Verificación controlada del forward y replay

Alcance de evidencia: `CONTROLLED_FORWARD_REPLAY`. Es una descripción de las
pruebas; no cambia los flags de aprobación del producto.

`tests/python/test_forward_replay_lifecycle.py` ejecuta `ForwardShadowBot.run`
con un cliente de lectura que ofrece account/terminal/symbol_info/ticks y barras
en el formato de MT5. La ruta real normaliza M5/M15/H1, construye features y usa
ensemble, perfiles, riesgo, ML explícitamente deshabilitado para investigación,
portfolio, límites, fills y ledger. El replay recibe las mismas cotizaciones y
barras canónicas. La prueba principal no sustituye `_scan_new_paper_trades`,
`_evaluate_paper_decision`, la estrategia ni el motor de riesgo.

Los episodios comparan traces completos, operaciones persistidas normalizadas
(solo se excluye el UUID de almacenamiento), PnL, equity, riesgo abierto,
referencia diaria, pausas y motivos de rechazo:

- Gap de SL y límite diario; cierre por TP; BE/trailing y cierre posterior.
- Repetición de la misma vela y ausencia de cotizaciones.
- Evidencia broker obsoleta.
- Dos símbolos con exposición real y límite de una/dos posiciones.
- Fallos en persistencia de señal, auditoría posterior al fill y final del ciclo.

Otras regresiones comprueban lectura de cuenta/conexión por ciclo, preservación
de pausa manual, reanudación diaria condicionada, moneda ausente/incorrecta,
auditoría de adquisición fallida y auditoría del halt fallida seguida de un
reinicio. `test_forward_lifecycle_review.py` contiene reproducciones
independientes de gestión parcial, cambio de cuenta/conexión y persistencia
incompleta. Sus pruebas de adquisición tienen un seam de barras explícito; el
archivo principal anterior sí atraviesa la normalización de barras del reader.

Comando de validación enfocado:

```powershell
py -3.14 -B -m pytest tests/python/test_forward_replay_lifecycle.py tests/python/test_forward_lifecycle_review.py tests/python/test_stateful_replay.py tests/python/test_stateful_replay_review.py tests/python/test_shared_decision_core.py tests/python/test_recorded_decision_replay.py -q
```

Las pruebas usan directorios temporales aislados, datos sintéticos y un reloj
inyectado. No acceden a un terminal ni Telegram, no importan un modelo local
posterior y no llaman `order_check`/`order_send`. No prueban origen histórico de
metadata/costes, fills de broker, robustez estadística o rentabilidad. La familia
ACTIVE y los scores de la oscilación sintética son controles deterministas,
no una selección de parámetros para demostrar rendimiento. Los gates de
perfiles MICRO/STABLE mantienen sus pruebas propias, pero esta comparación
completa de episodios económicos solo cubre ACTIVE; no certifica todas las
combinaciones de perfil, overlay, reanudación y modelo ML. La política de
referencia exacta de medianoche puede bloquear un forward que no haya capturado
ese instante; no se declara resuelto mediante interpolación.
