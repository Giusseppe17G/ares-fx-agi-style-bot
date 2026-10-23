# Guia de uso: puesta en marcha en Windows con cuenta demo

Version del 2026-10-10. Esta guia usa solo comandos verificados en el codigo
actual. Para el detalle tecnico ver `PROJECT_SPEC.md` (seccion 17.3),
`docs/decisions/2026-10-10-operational-forward-shadow.md` y
`docs/decisions/2026-10-10-declared-mt5-server-time.md`.

## Que hace el bot y que no hace

- **Hace:** lee datos de MetaTrader 5 (solo lectura), evalua senales con
  riesgo, simula operaciones en papel (paper trading) en una base SQLite,
  registra cada senal aceptada o rechazada con su motivo, y genera informes de
  estado, salud y evidencia. Opcionalmente avisa por Telegram.
- **No hace:** no envia, no comprueba ni construye ordenes al broker. Esa
  capacidad esta eliminada de esta version y no hay ningun interruptor para
  activarla. `DEMO_ONLY=True` y `LIVE_TRADING_APPROVED=False` no se pueden
  cambiar: la configuracion rechaza otros valores.
- **No esta listo para dinero real ni para operar en demo.** La estrategia
  intradia actual no supera a entradas aleatorias en los datos disponibles
  (`docs/research/trend-pullback-predeclared-v1-baselines.md`), y las primas
  lentas diarias (tendencia de 12 meses, carry y su mezcla) tampoco pasan un
  estudio predeclarado dentro de los limites de riesgo del bot (seccion 10).
  El objetivo de esta guia es ponerlo a observar en papel con una cuenta demo
  y reunir la evidencia que exige el Strategy Promotion Gate.

## 1. Requisitos

- Windows 10/11 o Windows Server con sesion de escritorio (el terminal MT5 debe
  estar abierto en la misma sesion de usuario).
- MetaTrader 5 instalado y con sesion iniciada en una **cuenta demo**, con los
  simbolos que vayas a usar visibles en "Observacion del mercado". No hace falta
  activar "Trading algoritmico": el bot nunca opera.
- Git para Windows: `winget install --id Git.Git -e`.
- Python 3.14 de 64 bits (x64) con el lanzador `py`:
  `winget install --id Python.Python.3.14 -e --architecture x64`. Pon
  `--architecture x64` tambien en Windows ARM: el paquete `MetaTrader5` solo
  existe para x64. Es la version que valida la CI. Python 3.11-3.13 x64 ejecutan
  los comandos de esta guia, pero la suite de pruebas y la comprobacion de
  fixtures nativos solo pasan con 3.14.
- Reloj de Windows sincronizado ("Configuracion > Hora e idioma > Sincronizar
  ahora", o `w32tm /resync` como administrador). Un tick que parece llegar del
  futuro se descarta, aunque sea por un segundo.
- Opcional, solo para el EA nativo: PowerShell 7 (`winget install --id Microsoft.PowerShell -e`).

## 2. Instalacion

En PowerShell:

```powershell
git clone https://github.com/Giusseppe17G/ares-fx-agi-style-bot.git
cd ares-fx-agi-style-bot
powershell -ExecutionPolicy Bypass -File .\scripts\windows_setup.ps1
```

`windows_setup.ps1` crea `.venv`, instala el proyecto con las versiones de
`constraints.txt` y el paquete `MetaTrader5`, comprueba que se importa y crea
las carpetas de `data`. No pide ni guarda secretos.

**En cada consola nueva**, dentro de la carpeta del proyecto, ejecuta primero
estas dos lineas (la primera permite los scripts `.ps1` solo en esa consola):

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
$env:PYTHONPATH = "src/python"
```

Comprobacion rapida, sin MetaTrader:

```powershell
.\.venv\Scripts\python.exe -m agi_style_forex_bot_mt5.cli --mode core-invariants
.\.venv\Scripts\python.exe -m agi_style_forex_bot_mt5.cli --mode shadow --sqlite data\sqlite\smoke.sqlite3
```

`core-invariants` debe mostrar `"order_send_called": false` y `"paper_only": true`.
`--mode shadow` (y `--mode demo`) es una prueba sintetica: usa un EURUSD de
ejemplo y una cuenta ficticia, no toca MT5 ni tu cuenta.

## 3. Configuracion

Sin archivo de configuracion se usan los valores seguros de
`config/defaults.example.ini`. Para cambiar algo crea un archivo **fuera del
repositorio** con solo las lineas que cambias; el resto conserva su valor por
defecto. Escribe las claves exactamente como en `config/defaults.example.ini`:
una clave mal escrita se ignora sin aviso, y una clave repetida, una linea sin
`=` o una cabecera de seccion como `[bot]` termina con codigo 2. Los limites de riesgo por operacion y abierto, los
drawdowns diario y flotante, las operaciones abiertas y la edad de ticks y
senales solo pueden ser iguales o mas estrictos que los de por defecto (otro
valor termina con codigo 2). `MAX_SPREAD_POINTS_DEFAULT` y
`MAX_PAPER_TRADES_PER_DAY` no tienen tope en Python: no los aumentes.

**Hora del servidor del broker (importante).** MetaTrader 5 entrega la hora de
los ticks y las barras en la hora del servidor del broker. Muchos brokers usan
UTC+2 en invierno y UTC+3 en verano (cierre de Nueva York). Si no lo declaras,
cada cotizacion parece llegar del futuro y el bot se detiene con el codigo 5.
Valores de `MT5_SERVER_TIME`:

- `UTC` (por defecto): el broker usa UTC.
- `NY_CLOSE`: UTC+2 en invierno y UTC+3 mientras EE. UU. tiene horario de
  verano (cierre de Nueva York). Es lo habitual.
- `EET`: UTC+2 en invierno y UTC+3 en el horario de verano europeo. Usalo si tu
  broker dice que sigue el horario europeo; las dos opciones solo difieren unas
  semanas en marzo y en octubre/noviembre.
- `UTC+02:00`, `UTC+03:00`, etc.: una hora fija sin cambio de verano.

La seccion 4 te dice cual necesitas. Crea el archivo antes de usar `--config`
(si tu broker usa UTC basta con `MT5_SERVER_TIME=UTC`): una ruta de `--config`
que no existe termina con codigo 2. Por ejemplo:

```powershell
New-Item -ItemType Directory -Force C:\ares-config | Out-Null
Set-Content -Path C:\ares-config\bot.ini -Value "MT5_SERVER_TIME=NY_CLOSE" -Encoding ASCII
```

- Los simbolos no se configuran en ese archivo: se eligen con `--symbols` o con
  `-Symbols` en los scripts. Los scripts usan por defecto `EURUSD,GBPUSD,USDJPY`;
  la CLI sin `--symbols` usa ocho pares (EURUSD, GBPUSD, USDJPY, USDCAD, USDCHF,
  AUDUSD, EURJPY, NZDUSD).
- Telegram (opcional): define las variables de entorno en la consola y anade
  `--telegram` (o `-Telegram` en los scripts). No las escribas en ningun archivo
  del repositorio; un archivo `.env` no se lee.

```powershell
$env:TELEGRAM_BOT_TOKEN = "<token de tu bot>"
$env:TELEGRAM_CHAT_ID = "<tu chat id>"
```

## 4. Comprobar la conexion y la hora del servidor (solo lectura)

Con el terminal abierto, conectado y **con el mercado abierto** (de domingo
noche a viernes noche):

```powershell
.\.venv\Scripts\python.exe -m agi_style_forex_bot_mt5.cli --mode mt5-diagnose --symbols EURUSD,GBPUSD,USDJPY --sqlite data\sqlite\mt5-diagnose.sqlite3 --config C:\ares-config\bot.ini
```

Por cada simbolo revisa:

- `status` = `PASSED`, `tick_time_status` = `FRESH` y `tick_age_seconds` entre
  0 y 5.
- `server_time_hint` vacio. Si dice que los ticks van 7200 o 10800 s por
  delante, pon `MT5_SERVER_TIME=NY_CLOSE` (o `EET`, o la hora fija que documente
  tu broker) y repite. Si dice que van horas atrasados, la declaracion sobra o es
  incorrecta.
- `FUTURE_TOO_FAR` con unos pocos segundos negativos: sincroniza el reloj de
  Windows.
- `MARKET_CLOSED_OR_NO_TICKS`: mercado cerrado; repite con el mercado abierto.

Codigo de salida 3 = MT5 no conectado (terminal cerrado, sin sesion o paquete no
instalado); el motivo queda en `data\logs`.

## 5. Observacion en papel (forward-shadow)

```powershell
.\scripts\run_forward_shadow.ps1 -Config C:\ares-config\bot.ini -Telegram
```

(Sin Telegram, quita `-Telegram`; sin archivo de configuracion, quita `-Config ...`.)

- Cada 30 s lee cotizaciones y barras, mide la calidad del broker y la
  correlacion con las posiciones abiertas, evalua la estrategia y el riesgo, y
  abre, gestiona o cierra operaciones **en papel**. Base de datos:
  `data\sqlite\forward-shadow.sqlite3`; registros: `data\logs\forward-shadow`.
- Un simbolo sin barras suficientes en alguna de las tres temporalidades (M5,
  M15, H1) se rechaza en ese ciclo (`MARKET_DATA_REJECTED`). Un diferencial por
  encima del limite baja su puntuacion de calidad.
- Con el mercado cerrado o el terminal desconectado registra
  `PAPER_CYCLE_SKIPPED` con el motivo, no toca el libro y reintenta con espera
  creciente (hasta 5 minutos). Telegram avisa, con el motivo (`reject_code`), al
  empezar cada racha y cuando cambia el motivo, y con `PAPER_CYCLE_RESUMED`
  cuando vuelve a completar ciclos. Tambien avisa al arrancar y al parar.
- Si un simbolo deja de pasar la comprobacion de integridad mientras los demas
  siguen, se excluye en cada ciclo y Telegram avisa una vez
  (`QUOTE_INTEGRITY_REJECTED`) hasta que vuelva a cotizar con normalidad.
- **Codigo 5:** las cotizaciones no pasaron la comprobacion de integridad (casi
  siempre `MT5_SERVER_TIME` o el reloj del PC). No se modifico nada: corrige y
  vuelve a lanzarlo sobre la misma base. El motivo por simbolo esta en el evento
  `FORWARD_SHADOW_INTEGRITY_STOP`.
- **Codigo 4:** el ciclo de papel quedo bloqueado (por ejemplo una cuenta real,
  un fallo de almacenamiento o un proceso matado a mitad de ciclo). El bloqueo
  es **permanente en esa base**: ni `resume-shadow` ni reiniciar lo quitan.
  El motivo esta en `lifecycle_halt_reason` de `paper-state-report` (seccion 6)
  y en `halt_reason` de `.\scripts\status.ps1`. Conserva esa base
  y `data\logs\forward-shadow` como evidencia y continua con otra base:
  `.\scripts\run_forward_shadow.ps1 -Config C:\ares-config\bot.ini -SqlitePath data\sqlite\forward-shadow-2.sqlite3 -LogDir data\logs\forward-shadow-2`.
  Usa esas mismas rutas en los comandos de seguimiento y parada.
- Para dejarlo funcionando con reinicio automatico, en lugar de
  `run_forward_shadow.ps1` lanza el watchdog en su propia ventana:

```powershell
Start-Process powershell -ArgumentList '-NoProfile -ExecutionPolicy Bypass -File .\scripts\watchdog_forward_shadow.ps1 -Config C:\ares-config\bot.ini -Telegram'
```

  El watchdog relanza el bot con cualquier codigo distinto de 0, 2, 4 y 5 (por
  ejemplo 1 si se cae); sin `-MaxCycles` el bot no sale al perder MT5, reintenta
  solo. Se detiene sin relanzar tras una parada pedida (0), argumentos o
  configuracion invalidos o un arranque imposible, como falta de `.venv` o del
  archivo de `-Config` (2), un bloqueo (4) o un fallo de integridad (5). Su
  registro esta en `data\logs\watchdog`. Las variables de Telegram de la consola
  se heredan.

## 6. Seguimiento

```powershell
.\scripts\status.ps1
.\.venv\Scripts\python.exe -m agi_style_forex_bot_mt5.cli --mode health --sqlite data\sqlite\forward-shadow.sqlite3 --log-dir data\logs\forward-shadow
.\.venv\Scripts\python.exe -m agi_style_forex_bot_mt5.cli --mode paper-state-report --sqlite data\sqlite\forward-shadow.sqlite3 --log-dir data\logs\forward-shadow --output-dir data\reports\paper_state
.\.venv\Scripts\python.exe -m agi_style_forex_bot_mt5.cli --mode daily-summary --sqlite data\sqlite\forward-shadow.sqlite3 --log-dir data\logs\forward-shadow
```

- `status`, `health` y `paper-state-report` no modifican la base
  (`paper-state-report` escribe su informe en `data\reports\paper_state`). Si
  `paper-state-report` dice `PAPER_CYCLE_IN_PROGRESS` con el bot en marcha, es un
  ciclo en curso: repitelo. `PAPER_LIFECYCLE_HALTED` es el bloqueo del codigo 4.
  `daily-summary` si escribe: guarda el resumen en la base y deja
  `data\reports\backtests\<fecha>-summary.json` y `.html`.
- Si la ruta de `--sqlite` es incorrecta, estos comandos crean una base vacia y
  terminan con codigo 0: revisa la ruta.
- `forward-acceptance` es la puerta del perfil `BALANCED_STABLE`; en esta
  observacion generica responde normalmente `PAUSE_FORWARD_SHADOW` con "Stable
  gate is missing.", que no indica un fallo. Si `reason` es otro (drawdown
  diario o recuperacion del estado de papel), revisalo con `paper-state-report`
  antes de seguir. `NEEDS_TELEMETRY_FIX` o `NEEDS_TELEMETRY_REVIEW` indican
  marcas de tiempo invalidas: revisalas con `--mode telemetry-status` (mismas
  `--sqlite` y `--log-dir`).

## 7. Parar y reanudar

- En la consola donde corre: `Ctrl+C` **una vez**. Termina el ciclo en curso, se
  detiene (`"exit_reason": "STOP_REQUESTED"`, codigo 0) y muestra su resultado.
  Un segundo `Ctrl+C` lo aborta a mitad de ciclo, y eso puede bloquear la base
  (codigo 4 al volver a lanzarlo).
- Desde otra consola (detiene tambien el watchdog):

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\stop_forward_shadow.ps1
```

  Pide la parada, espera a que termine el ciclo en curso (hasta 180 s) y
  confirma "stopped cleanly". Las posiciones de papel abiertas se conservan. Si
  no encuentra ni el bot ni el watchdog de esa base lo dice y termina con codigo
  1. Si
  no termina a tiempo, la peticion queda pendiente: vuelve a ejecutarlo mas
  tarde. `-Force` mata el proceso, y solo debe usarse como ultimo recurso.
  Con otra base, anade `-SqlitePath ...` (cualquier forma de escribir la misma
  ruta sirve).
- Para reanudar, lanza el mismo comando de la seccion 5. Solo si pausaste a mano
  con `--mode pause-shadow` hace falta antes
  `--mode resume-shadow --sqlite data\sqlite\forward-shadow.sqlite3 --reason "reanudacion revisada"`.

## 8. Reunir la evidencia que falta

El protocolo `docs/testing/next-evidence-protocol.md` necesita datos nuevos de
tu broker demo, sin identificadores personales:

1. Barras historicas en CSV (solo lectura). Usa la misma `--config` (debe
   existir; si no, codigo 2): las horas se guardan en UTC segun
   `MT5_SERVER_TIME`.

```powershell
.\.venv\Scripts\python.exe -m agi_style_forex_bot_mt5.cli --mode export-history --symbols EURUSD,GBPUSD,USDJPY --timeframes M5,M15,H1 --bars 50000 --output-dir data\historical --config C:\ares-config\bot.ini
```

2. Especificacion de instrumentos. Crea `data\runtime\symbol_map.json` con el
   nombre exacto de cada simbolo en tu broker y captura con un nombre de salida
   nuevo (nunca se sobrescribe uno existente):

```powershell
New-Item -ItemType Directory -Force data\runtime | Out-Null
[IO.File]::WriteAllText("$PWD\data\runtime\symbol_map.json", '{"EURUSD": "EURUSD", "GBPUSD": "GBPUSD", "USDJPY": "USDJPY"}')
.\.venv\Scripts\python.exe -m agi_style_forex_bot_mt5.cli --mode build-instrument-registry --broker-symbol-map data\runtime\symbol_map.json --instrument-registry-output "data\runtime\instrument_registry-$(Get-Date -Format yyyyMMdd-HHmmss).json"
```

3. Comisiones: anotalas a mano desde "Especificacion" del simbolo en MT5, con
   fecha y fuente. El swap se registra con el comando de la seccion 11 (el
   snapshot de instrumentos no lo incluye).
4. La observacion forward-shadow de al menos dos semanas o 200 operaciones de
   papel (lo que tarde mas), con sus carpetas `data\sqlite` y `data\logs`.

Antes de compartir cualquier archivo, comprueba que no contiene tu numero de
cuenta ni nombres de servidor.

## 9. EA nativo y harness matematico (opcional)

Requieren PowerShell 7 y MetaTrader 5 instalado en `C:\Program Files\MetaTrader 5`.
Si esta en otra carpeta usa `compile_native_observer.ps1 -MetaEditor "<carpeta>\MetaEditor64.exe"`
y `run_native_math_harness.ps1 -InstallDirectory "<carpeta>"`. Compilan en una
carpeta temporal y no instalan nada en el terminal:

```powershell
pwsh -NoProfile -File .\scripts\compile_native_observer.ps1
pwsh -NoProfile -File .\scripts\run_native_math_harness.ps1
```

El segundo inicia una copia portable del terminal en modo matematico del
Strategy Tester, sin cuenta. Detalle en `docs/testing/native-math-harness.md`.

## 10. Estudio diario de primas lentas (investigacion, opcional)

Resultado del 2026-10-17: tendencia de 12 meses, carry y su mezcla sobre
EUR, JPY, GBP, CHF, CAD, AUD, NZD, SEK y NOK contra USD, simulados dia a dia
dentro de los limites del bot (0,5% de riesgo por posicion, 5% de riesgo
abierto, 10 posiciones, SL y TP siempre) con un plan congelado antes de ver
resultados. Las tres hipotesis quedan **rechazadas** en el periodo de
desarrollo 1999-2016 (mejor t de Newey-West 0,62 frente al minimo de 2,0) y
el periodo reservado 2017-2026 no se evaluo: sigue disponible para una idea
nueva, que debe predeclararse antes de mirarlo. Detalle y cifras:
`docs/research/daily-fx-slow-premia-predeclared-v1.md`.

Para reproducir el desarrollo hacen falta los mismos archivos de datos (la
copia de FRED H.10 de github.com/datasets/exchange-rates en el commit
c023dd8b8f87 y el CSV de tipos OECD indicado en el documento; clona con
`git clone -c core.autocrlf=false` para no alterar el sha256) y las mismas
versiones de Python, numpy y pandas; si no coinciden, el runner se niega con
codigo 2. El motor se corrigio despues de esa ejecucion, asi que el plan v1
solo se reproduce con el codigo del commit b264293 (vuelve a `main` al
terminar). El plan original y su ledger ya tienen el desarrollo registrado, asi
que se reproduce sobre copias:

```powershell
git switch --detach b264293
New-Item -ItemType Directory -Force data\runs\daily_fx_repro | Out-Null
Copy-Item docs\research\daily_fx_slow_premia_v1\plan.json data\runs\daily_fx_repro\plan.json
.\.venv\Scripts\python.exe -m agi_style_forex_bot_mt5.research.daily_fx.runner development --prices data\historical\fred\daily.csv --rates data\historical\oecd\short-term-interest.csv --plan-file data\runs\daily_fx_repro\plan.json --ledger data\runs\daily_fx_repro\ledger.jsonl
git switch main
```

Segundo estudio (2026-10-23, plan v2): valor real a 5 anos sobre AUD, CAD,
CHF, DKK, GBP, JPY, NOK, NZD y SEK, con el USD como decima divisa ordenada.
El libro compra las 3 divisas mas baratas en terminos reales (precio frente a
su nivel de hace 4,5-5,5 anos, corregido por la inflacion anual del Banco
Mundial) y vende las 3 mas caras, cada una con 0,5% de riesgo hasta su stop.
Solo precio: no acredita el carry.

Resultado en desarrollo (1985-2016):

- Pasa 12 de 13 compuertas: Sharpe neta 0,39, t de Newey-West 2,06, positivo
  en 1985-1998 y en 1999-2016, mejor que las 200 carteras con divisas
  permutadas, Sharpe 0,17 con costes duplicados, caida maxima 6,1%.
- Falla la Sharpe deflactada, que cuenta las 8 pruebas del programa: 0,77
  frente a 0,95.
- Queda **rechazado** y el periodo reservado no se evaluo.
- Es el mejor resultado obtenido hasta ahora, pero no basta para descartar
  que sea suerte entre los intentos hechos.

Detalle: `docs/research/daily-fx-real-value-predeclared-v2.md`.

El plan v2 necesita ademas el CSV de inflacion del Banco Mundial
(github.com/datasets/cpi, commit 3750e450, `data/cpi.csv`, sha256 182baa44...)
copiado en `data/historical/worldbank/cpi.csv`. Para reproducir el desarrollo
hace falta el ledger compartido hasta la cabeza registrada (sus 11 primeras
lineas), no un ledger vacio:

```powershell
New-Item -ItemType Directory -Force data\runs\daily_fx_v2_repro | Out-Null
Copy-Item docs\research\daily_fx_real_value_v2\plan.json data\runs\daily_fx_v2_repro\plan.json
.\.venv\Scripts\python.exe -c "lines = open('docs/research/trial_ledger.jsonl', encoding='utf-8').readlines()[:11]; open('data/runs/daily_fx_v2_repro/ledger.jsonl', 'w', encoding='utf-8', newline='\n').writelines(lines)"
.\.venv\Scripts\python.exe -m agi_style_forex_bot_mt5.research.daily_fx.runner development --plan real_value_v2 --prices data\historical\fred\daily.csv --inflation data\historical\worldbank\cpi.csv --plan-file data\runs\daily_fx_v2_repro\plan.json --ledger data\runs\daily_fx_v2_repro\ledger.jsonl
```

Nada de esto lee el terminal ni envia ordenes.

## 11. Registrar el swap del broker (solo lectura)

Hasta ahora el coste de financiacion (swap) era un supuesto: el estudio diario
cargaba un margen de 75 pb al ano. Este comando guarda los terminos de swap que
publica tu broker para medir el coste real a lo largo del tiempo. Usa el mismo
mapa de simbolos de la seccion 8, la misma `--config` (se guarda el
`MT5_SERVER_TIME` declarado) y un nombre de salida nuevo con fecha y hora (nunca
se sobrescribe uno existente y la carpeta debe existir):

```powershell
.\.venv\Scripts\python.exe -m agi_style_forex_bot_mt5.cli --mode capture-swap-snapshot --broker-symbol-map data\runtime\symbol_map.json --swap-snapshot-output "data\runtime\swap_snapshot-$(Get-Date -Format yyyyMMdd-HHmmss).json" --config C:\ares-config\bot.ini
```

Solo llama a `initialize`, `symbol_info` y `shutdown`: no lee la cuenta ni
envia ordenes. Por cada simbolo guarda `swap_long`, `swap_short`, el modo de
swap (`swap_mode` y su nombre, por ejemplo `POINTS`), el dia del triple swap,
las monedas, el tamano del contrato, `point`, `digits` y el spread actual en
puntos, ademas de la hora UTC de captura y un `payload_sha256`. Revisa el JSON
de salida:

- `status` = `CAPTURED`: se registraron todos los simbolos.
- `PARTIAL`: alguno no; `unavailable` dice cual y por que (por ejemplo
  `SYMBOL_INFO_MISSING` si el nombre no coincide con el de tu broker, o
  `SWAP_MODE_UNKNOWN`). Los demas si quedan registrados.
- `UNAVAILABLE`: no se pudo registrar ninguno. El archivo se escribe igual
  (es evidencia de lo que respondio el broker), pero el comando sale con codigo
  3; revisa el mapa de simbolos y la sesion de MT5.
- `swap_terms_hash` cubre solo los terminos de los simbolos registrados
  (`CAPTURED`): no cambia con la hora, con el spread ni con el motivo por el que
  otro simbolo no se registro. Repite la captura, por ejemplo una vez por
  semana, y compara ese hash entre snapshots que registraron los mismos
  simbolos (por ejemplo dos `CAPTURED`) para saber cuando el broker cambio el
  swap. Si en uno falta un simbolo, el hash cambia porque cubre otro conjunto:
  compara entonces simbolo por simbolo.

Codigo 2: argumentos invalidos o destino existente o no escribible (se comprueba
antes de abrir MT5, salvo la escritura final). Codigo 3: MT5 no disponible, o
ningun simbolo registrado (`status` = `UNAVAILABLE`, con el archivo escrito).

Para convertir un swap en puntos en un porcentaje anual aproximado del nocional
pasa el precio actual de cada par (no se inventa ninguno). Solo se convierte el
modo `POINTS` de pares con USD; los cruces, los otros modos y los pares sin
precio salen como `UNAVAILABLE` con su motivo. El precio se comprueba: si su
escala no encaja con los `digits` del simbolo (por ejemplo 1.08 para USDJPY o
150 para EURUSD) sale `PRICE_SCALE_IMPLAUSIBLE`, y si el swap anual de un largo
o de un corto supera el 50% del nocional sale `ANNUAL_CARRY_IMPLAUSIBLE`, en
vez de un numero absurdo. Cambia el nombre del archivo por el que creaste:

```powershell
.\.venv\Scripts\python.exe -c "import json, sys; from agi_style_forex_bot_mt5.broker_swap_snapshot import read_swap_snapshot, snapshot_carry; print(json.dumps(snapshot_carry(read_swap_snapshot(sys.argv[1]), {'EURUSD': 1.08, 'USDJPY': 150.0}), indent=2))" data\runtime\swap_snapshot-20261022-213000.json
```

`long_annual_percent_of_notional` y `short_annual_percent_of_notional` son el
swap anual de un largo y de un corto (negativo = lo pagas). `OBSERVED` se
refiere solo a los terminos de swap del broker: el precio es el que tu pasaste
(`price_source` = `caller`, `price_observed` = `false`), asi que un precio
desactualizado mueve el porcentaje en la misma proporcion, y un precio con un
decimal mal puesto (10.8 en vez de 1.08 para EURUSD) no siempre se detecta y
divide el resultado por diez: comprueba el precio antes de usar la cifra.
`implied_symmetric_markup_bps_per_year` es el margen del broker si lo aplica por
igual a largos y cortos, comparable con los 75 pb supuestos. Es una
aproximacion: ignora los festivos con rollover extra y los cambios de terminos
durante el ano. Nada de esto cambia todavia los backtests ni las decisiones.

## Codigos de salida

| Codigo | Significado |
| --- | --- |
| 0 | Completado (o forward-shadow parado a peticion); el JSON de salida tiene el detalle. |
| 1 | Error no controlado; la traza indica la causa. |
| 2 | Argumentos o configuracion invalidos (por ejemplo `DEMO_ONLY=False`, una clave repetida o una ruta de `--config` que no existe), destino del snapshot ya existente (o no escribible en `capture-swap-snapshot`), forward-shadow ya en marcha sobre esa base o, en los scripts `run_forward_shadow.ps1` (y el watchdog), `status.ps1` y `stop_forward_shadow.ps1`, falta de `.venv`. |
| 3 | MT5 no disponible (paquete ausente, terminal cerrado o sin sesion) en `mt5-data`, `mt5-diagnose`, `export-history`, `build-instrument-registry` y `capture-swap-snapshot`; `capture-swap-snapshot` sin ningun simbolo registrado (`status` = `UNAVAILABLE`; el archivo se escribe igual); o `forward-shadow` con `-MaxCycles` sin ningun ciclo completado (sin `-MaxCycles` reintenta indefinidamente). |
| 4 | forward-shadow: ciclo de papel bloqueado de forma permanente en esa base (seccion 5). |
| 5 | forward-shadow: cotizaciones de MT5 sin integridad (`MT5_SERVER_TIME` o reloj del PC); nada se modifico. |

## Que falta para poder operar

Nada de esta guia habilita operaciones. Una version ejecutable en demo
necesita: una estrategia que supere el Strategy Promotion Gate acumulativo
(`PROJECT_SPEC.md` seccion 12.1) con datos no inspeccionados, la evidencia
forward de la seccion 8, una revision especifica de ejecucion y una nueva
decision de arquitectura. La cuenta real queda fuera del alcance del proyecto.
