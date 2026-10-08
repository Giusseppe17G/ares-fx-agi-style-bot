# Indicadores nativos puros: fixtures diferenciales

Contrato: `PROJECT_SPEC.md` §17.9, paquete `native_core_indicators_v1`.
Ámbito: indicadores y verificación numérica. No cambia estrategias, parámetros,
riesgo, ejecución, EA ni fuentes Python de producción. Todos los datos son
sintéticos; no se usan resultados de investigación ni cotizaciones de mercado.

## Evidencia entregada

- 49 casos sobre 16 historias: 23 bundles esperados válidos y 26 rechazos.
- 1.348 aserciones `Check` generadas para el harness MQL.
- 98 pruebas Python ejecutadas correctamente, incluyendo referencias reales,
  reproducibilidad exacta, procedencia de inputs y guardianes de fuente.
- Runtime de referencia: Python 3.14.4, pandas 3.0.2, NumPy 2.4.4,
  binary64 con 53 bits de precisión y exponente máximo 1024.

El JSON es la autoridad de los fixtures. Guarda historias, solicitudes completas,
mutaciones y rangos de entrada, hash de cada entrada expandida, observaciones
Python, expectativa nativa y presupuesto absoluto por indicador. El generador
invoca `closed_strategy_bars`, `ema`, `rsi` y `atr` reales. Conserva hashes del
código de esas funciones y de `validate_ohlcv_frame`, además de las versiones.
Las observaciones no implementan una copia Python del algoritmo MQL.

El include conserva el SHA256 del JSON:
`382b514f7b273601be92d176efc69da7a4eb4ffb65a7bdc3688e16aee82c25a2`.
SHA256 del include generado:
`2bdf82a62837fcc907f175c6e9f94c6a6ee69ccf79ec9b05f1b9b7d8d001d649`.

## Semántica contrastada

Se calcula desde la primera observación de todo el prefijo cerrado. EMA empieza
en el primer cierre; ATR, en el primer high-low; RSI, en la primera diferencia
real. Los periodos mínimos ocultan la salida inicial, sin reemplazar esa semilla
por una media simple. En índices desde cero, las primeras salidas son EMA20=19,
EMA50=49, EMA200=199, RSI14=14 y ATR14=13. La documentación de
[pandas EWM](https://pandas.pydata.org/docs/reference/api/pandas.DataFrame.ewm.html)
define la recurrencia con `adjust=False` y el significado de `min_periods`;
la referencia instalada se vincula también al
[código pandas v3.0.2](https://github.com/pandas-dev/pandas/blob/v3.0.2/pandas/_libs/window/aggregations.pyx).

El módulo nativo publica todos los valores juntos sólo si hay al menos 200
barras y se cumple el mínimo del request. Un prefijo de 199 barras conserva
algunas salidas Python individuales, pero el bundle nativo rechaza sin valores
parciales. El calentamiento de investigación de 250 barras sigue siendo otra
política: recortar a las últimas 250 observaciones cambia EMA200 respecto de
las 400 originales, aun compartiendo el mismo cierre final.

Los huecos de tiempo no agregan observaciones ni decaimiento temporal. Se
prueban M5/M15/H1 con precios idénticos y disponibilidad distinta. Los cambios
de volumen/spread no cambian estas cinco fórmulas, aunque dichos campos siguen
sujetos a la validación de entrada. ATR sí usa el cierre observado anterior
cuando existe un salto de precio. No se utiliza VWAP ni el builder de features
completo para fabricar estas expectativas.

## Cobertura y diferencias explícitas

- Prefijos de 1/13/14/15/19/20/21/49/50/51/199/200/201/250/400 barras,
  cierre exacto y un milisegundo antes de la barra 200.
- Constantes con rango cero y positivo, tendencias ascendentes/descendentes,
  alternancia, impulso, valores casi constantes, saltos y huecos de calendario.
- Historia completa frente a cola recortada; mutación válida de todo el futuro
  excluido; mismo prefijo sin las barras futuras; cambio explícito de símbolo.
- Valores muy grandes, pequeños y subnormales constantes. RSI sin pérdidas es
  100, sin ganancias es 0 y con ambas medias cero es 50. ATR cero es válido en
  este módulo y no constituye una señal ni una autorización de ejecución.
- Entradas NaN/Inf, OHLC inválido, volumen negativo, duplicados, solapamiento,
  historia vacía, snapshot futuro/viejo y mínimo del request incumplido.
- Todos los resultados se precargan con datos anteriores inválidos, incluidos
  flags verdaderos. Cada éxito va seguido de un request inválido y se comprueba
  que identidad, valores, tiempos y conteos se limpian íntegramente.

Las diferencias nativas llevan un `comparison_scope` y una explicación:
validación global de barras futuras, solapamiento, restricciones del request,
calentamiento del bundle y aritmética más estricta. Por ejemplo, los 200 cierres
`[2e-308, 1e-308] + [1e308] * 198` producen RSI Python final 100 por saturación
de un cociente infinito, pese a tener OHLC finito. La expectativa nativa es
`INDICATOR_ARITHMETIC_INVALID` antes de dividir. Esto documenta una restricción
del dominio; no se presenta como igualdad de resultados.

## Presupuesto numérico predeclarado

Para EMA/ATR, el error absoluto permitido es
`min(512 * ulp(valor_esperado), 1e-12 * abs(valor_esperado))`.
No tiene piso absoluto; cero exige cero y un presupuesto que underflowea a
cero exige coincidencia exacta. Para RSI, la tolerancia absoluta es `1e-10`
en su escala [0,100]. Estado, versión, identidad, conteos y timestamps son
exactos. Un resultado no finito nunca cumple la comparación.

Estos límites se fijaron antes de observar una ejecución MQL. Admiten pequeñas
diferencias de redondeo entre evaluaciones binary64 de recurrencias suavizadas;
el límite por ULP sigue la resolución local y el límite relativo impide un
presupuesto desproporcionado en subnormales. No son una demostración universal
de error, una equivalencia bit a bit ni un permiso para mover umbrales de
estrategia. Una divergencia requiere diagnóstico, no ampliar automáticamente
la tolerancia. Las propiedades del tipo y las comprobaciones de finitud están
documentadas por MetaQuotes en
[double](https://www.mql5.com/en/docs/basis/types/double) y
[MathIsValidNumber](https://www.mql5.com/en/docs/math/mathisvalidnumber).

## Reproducir

Desde la raíz del checkout, sin terminal ni datos externos:

```powershell
py -3.14 -B scripts/generate_native_core_indicator_fixtures.py --check
py -3.14 -B -m pytest tests/python/test_native_core_indicator_fixtures.py -q -p no:cacheprovider
```

Para regenerar, quitar `--check`. También se admiten `--json-output` y
`--mql-output`; las pruebas usan `tmp_path`, comprueban bytes exactos y detectan
artefactos obsoletos. Cambiar la versión de Python/pandas/NumPy o las funciones
referenciadas exige revisar y regenerar la evidencia, no aceptar silenciosamente
los números anteriores.

## Límites de certeza

El autor de estos fixtures no compiló ni ejecutó MQL. El harness incluye datos
y expectativas, pero las 1.348 aserciones sólo se ejecutan al correrlo en un
runtime MQL autorizado posteriormente. Compilar y pasar los guardianes de
fuente comprueba propiedades distintas; ninguno acredita esos resultados de
ejecución. Los guardianes son verificaciones estáticas acotadas, no una prueba
formal de pureza.

No se acredita paridad runtime, procedencia UTC de datos adquiridos, origen del
volumen, features completas, régimen, scoring, estrategia, riesgo, ejecución
ni rentabilidad. `execution_authorized` y `full_pipeline_verified` permanecen
false. Un consumidor futuro debe comprobar nuevamente la frescura al usar la
salida; una instancia vieja del resultado no autoriza su reutilización.
