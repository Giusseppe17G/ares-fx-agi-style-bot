# Bloqueo de capacidad de ejecucion broker en la release inicial

Estado: aceptado. Alcance: ejecucion, seguridad y compatibilidad.

La auditoria con clientes falsos reprodujo cuatro rutas inseguras: un
ExecutionEngine con BotConfig por defecto y shadow_mode=True enviaba; cambiar
shadow_mode=False enviaba sin evidencia de promocion; flags de live/whitelist
construidos directamente habilitaban la cuenta real simulada; order_send del
adapter admitia una llamada directa sin SL/TP ni verificacion de cuenta. Ninguna
reproduccion llamo un terminal MT5 ni envio una orden real.

Se elimina la capacidad de construir/check/send del adapter de esta release.
ExecutionEngine.execute devuelve siempre sent=False y filled=False antes de
consultar el cliente, construir request o iniciar retries. El codigo es
SHADOW_MODE_BLOCKED con shadow activado o sin booleano explicito False;
EXECUTION_NOT_RELEASED con shadow_mode=False. No existe bandera de escape, token
de prueba ni excepcion para clientes inyectados. Metadata promotion aprobada,
risk_decision.accepted, audit_confirmed o whitelist no conceden capacidad.

MT5Connector mantiene sus firmas publicas. build_trade_request lanza ValueError
con el codigo de bloqueo; order_check devuelve AdapterCheck rechazado;
order_send devuelve ExecutionResult no enviado. Estas rutas no acceden al
cliente nativo, ni siquiera a account_info o last_error. Las APIs de lectura y
diagnostico de volumen/stops/filling/retcodes permanecen disponibles. Los tests
antiguos de envio exitoso se sustituyen por rechazo de release y verificaciones
directas de esas primitivas; no se incorpora una ruta de envio solo para tests.

Compatibilidad: cambio semantico intencional y restrictivo. Consumidores que
esperaban ejecucion demo deben manejar el rechazo explicito. No se considera
listo un executor demo porque unos mocks puedan devolver TRADE_RETCODE_DONE.
La futura release ejecutable necesita revision especifica, Strategy Promotion
Gate reproducible, auditoria durable ligada a señal/decision/request/result,
idempotencia y reconciliacion frente al broker, riesgo actualizado al envio,
costes y tick grid correctos, y compilacion/pruebas MT5 completas. Esta decision
no establece que esas condiciones ya se hayan cumplido.

El bloqueo cubre las APIs soportadas del repositorio. Python no es un sandbox
contra codigo externo que importe MetaTrader5 directamente o altere clases en
memoria; las pruebas no prometen ese limite de aislamiento.

Verificacion: `tests/python/test_execution_release_lock.py`,
`test_execution_engine.py` y `test_integration_safety.py`, usando exclusivamente
clientes falsos. UntouchableClient falla ante cualquier acceso nativo; se
prueban flags shadow/demo/live/whitelist, auditoria arbitraria, promocion
declarada, repeticion, configuraciones inconsistentes y llamadas directas.
