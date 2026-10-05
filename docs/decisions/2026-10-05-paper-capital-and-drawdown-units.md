# Capital paper persistido y unidades del drawdown

Estado: implementado para investigacion/shadow; no habilita ejecucion demo/real.

## Contexto

Forward usaba el balance del broker como referencia nueva y no incorporaba el
libro paper completo. El monitor comparaba drawdown historico en moneda contra
un limite llamado diario del 3%. Esto ocultaba riesgo flotante y podia detener
el bot por perder 4 USD en una base de 10000 USD.

## Decision

Guardar una baseline paper unica solo con historia vacia. Los libros existentes
sin procedencia suficiente se bloquean hasta reconciliacion; no se presume su
capital original. Derivar balance de la baseline mas PnL cerrado verificable y
equity incluyendo cada abierto marcado con cotizacion/metadata fresca.

El lot persistido ya contiene las reducciones de riesgo. Los trades nuevos usan
`metadata.pnl_basis=APPROVED_LOT_UNSCALED_V1`, con formula de cierre
`paper_pnl_approved_lot_v1`; no se multiplican otra vez PnL o drawdown. El nombre
de la clave evita el token sensible `account` para conservar el redactor actual.

Las referencias diarias usan UTC, quedan persistidas y releidas, y retienen el
halt tras recuperacion hasta el siguiente dia. Si hay posiciones atravesando
medianoche sin equity de frontera, no se inventa esa referencia. Un indice de
historia impide que una llamada olvide trades ya observados.

Guardar la ultima valoracion con hash del libro economico y fecha. El monitor
solo considera VERIFIED una valoracion de hasta cinco segundos para el libro
actual. Sin referencia/valoracion verificada reporta UNKNOWN y cifras null,
ademas de alerta de datos ausentes cuando existe evidencia de trades.

Los porcentajes diario/flotante permanecen separados del drawdown historico en
moneda. Los limites del proyecto permanecen 3% diario y 5% flotante; el valor
monetario no activa esos umbrales. `drawdown_paper` es ahora un alias negativo
del porcentaje diario verificado; consumidores antiguos deben consultar status
y unidad. El historico se conserva como historical_drawdown_amount/currency.

## Consecuencias y validacion

No se reescribe evidencia legacy ni se inventan conversiones de monedas. Un
solo escritor forward-shadow debe poseer cada base; la API actual de store no
ofrece compare-and-swap multiproceso. No se afirma que un snapshot actual pruebe
metadata historica o que una fuente no verificada denomine tick_value bien.

Pruebas reproducibles y limites en
[estado paper](../testing/paper-decision-state-validation.md) y
[metricas](../testing/paper-drawdown-metrics-validation.md). Toda verificacion usa
temporales y mocks, sin terminal ni operaciones de broker.
