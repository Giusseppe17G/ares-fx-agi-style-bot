# Guia de uso: puesta en marcha en Windows con cuenta demo

Version del 2026-10-10. Esta guia usa solo comandos verificados en el codigo
actual. Para el detalle tecnico ver `PROJECT_SPEC.md` y
`docs/decisions/2026-10-10-operational-forward-shadow.md`.

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
  actual no supera a entradas aleatorias en los datos disponibles
  (`docs/research/trend-pullback-predeclared-v1-baselines.md`). El objetivo de
  esta guia es ponerlo a observar en papel con una cuenta demo y reunir la
  evidencia que exige el Strategy Promotion Gate.

## 1. Requisitos

- Windows 10/11 o Windows Server con sesion de escritorio (el terminal MT5 debe
  estar abierto en la misma sesion de usuario).
- MetaTrader 5 instalado y con sesion iniciada en una **cuenta demo**, con los
  simbolos que vayas a usar visibles en "Observacion del mercado". No hace falta
  activar "Trading algoritmico": el bot nunca opera.
- Git para Windows: `winget install --id Git.Git -e`.
- Python 3.14 de 64 bits con el lanzador `py`:
  `winget install --id Python.Python.3.14 -e`. Es la version que valida la CI y
  tiene paquete `MetaTrader5` para Windows. Python 3.11-3.13 tambien funcionan.
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

Comprobacion rapida, sin MetaTrader (en cada consola nueva, primero la linea de
`PYTHONPATH`):

```powershell
$env:PYTHONPATH = "src/python"
.\.venv\Scripts\python.exe -m agi_style_forex_bot_mt5.cli --mode core-invariants
.\.venv\Scripts\python.exe -m agi_style_forex_bot_mt5.cli --mode shadow --sqlite data\sqlite\smoke.sqlite3
```

`core-invariants` debe mostrar `"order_send_called": false` y `"paper_only": true`.
`--mode shadow` (y `--mode demo`) es una prueba sintetica: usa un EURUSD de
ejemplo y una cuenta ficticia, no toca MT5 ni tu cuenta.

## 3. Configuracion opcional

- No hace falta archivo de configuracion: los valores por defecto son los
  seguros de `config/defaults.example.ini`. Si quieres cambiar algo permitido
  (por ejemplo simbolos o limites mas estrictos), copia ese archivo fuera del
  repositorio y pasalo con `--config`. Debe estar en UTF-8.
- Telegram: define las variables de entorno de la sesion y anade `--telegram`.
  No las escribas en ningun archivo del repositorio. Un archivo `.env` no se lee.

```powershell
$env:TELEGRAM_BOT_TOKEN = "<token de tu bot>"
$env:TELEGRAM_CHAT_ID = "<tu chat id>"
```

## 4. Comprobar la conexion con MT5 (solo lectura)

Con el terminal abierto y conectado:

```powershell
.\.venv\Scripts\python.exe -m agi_style_forex_bot_mt5.cli --mode mt5-diagnose --symbols EURUSD,GBPUSD,USDJPY --sqlite data\sqlite\mt5-diagnose.sqlite3
```

Revisa `mt5_connected` y, por simbolo, el diferencial, la edad del tick y el
desfase horario del broker. Codigo de salida 3 = MT5 no conectado (terminal
cerrado, sin sesion o paquete no instalado); el motivo queda en `data\logs`.

## 5. Observacion en papel (forward-shadow)

```powershell
.\scripts\run_forward_shadow.ps1 -Symbols "EURUSD,GBPUSD,USDJPY"
```

- Cada 30 s lee cotizaciones y barras, mide la calidad del broker y la
  correlacion con las posiciones abiertas, evalua la estrategia y el riesgo, y
  abre, gestiona o cierra operaciones **en papel**. Base de datos:
  `data\sqlite\forward-shadow.sqlite3`; registros: `data\logs\forward-shadow`.
- Con el mercado cerrado o el terminal desconectado registra
  `PAPER_CYCLE_SKIPPED` con el motivo, no toca el libro y reintenta con espera
  creciente (hasta 5 minutos). No hace falta reiniciar nada.
- Si se detiene con codigo 4, el ciclo de papel quedo bloqueado por un fallo
  que requiere revision (por ejemplo una cuenta real o un fallo de
  almacenamiento). Revisa `paper-state-report` (seccion 6) antes de seguir.
- Para dejarlo funcionando con reinicio automatico usa
  `.\scripts\watchdog_forward_shadow.ps1` en lugar de `run_forward_shadow.ps1`.
- La primera vez que el mercado abra, la evidencia de calidad del broker se
  mide en cada ciclo; un simbolo que no tenga las tres temporalidades (M5, M15,
  H1) o con el diferencial por encima del limite pierde puntuacion.

## 6. Seguimiento

```powershell
.\scripts\status.ps1
.\.venv\Scripts\python.exe -m agi_style_forex_bot_mt5.cli --mode health --sqlite data\sqlite\forward-shadow.sqlite3 --log-dir data\logs\forward-shadow
.\.venv\Scripts\python.exe -m agi_style_forex_bot_mt5.cli --mode daily-summary --sqlite data\sqlite\forward-shadow.sqlite3 --log-dir data\logs\forward-shadow
.\.venv\Scripts\python.exe -m agi_style_forex_bot_mt5.cli --mode paper-state-report --sqlite data\sqlite\forward-shadow.sqlite3 --log-dir data\logs\forward-shadow --output-dir data\reports\paper_state
.\.venv\Scripts\python.exe -m agi_style_forex_bot_mt5.cli --mode forward-acceptance --sqlite data\sqlite\forward-shadow.sqlite3 --log-dir data\logs\forward-shadow
```

Todos son de solo lectura sobre la base de datos y los registros.

## 7. Parar y reanudar

- Si lo lanzaste en una consola: `Ctrl+C`.
- Desde otra consola (tambien detiene el watchdog generico):
  `.\scripts\stop_forward_shadow.ps1`. Primero pausa las entradas nuevas en la
  base de datos y despues detiene los procesos; las posiciones de papel abiertas
  se conservan.
- Antes de volver a arrancar tras `stop_forward_shadow.ps1`:

```powershell
.\.venv\Scripts\python.exe -m agi_style_forex_bot_mt5.cli --mode resume-shadow --sqlite data\sqlite\forward-shadow.sqlite3 --reason "reanudacion revisada"
```

## 8. Reunir la evidencia que falta

El protocolo `docs/testing/next-evidence-protocol.md` necesita datos nuevos de
tu broker demo, sin identificadores personales:

1. Barras historicas en CSV (solo lectura):

```powershell
.\.venv\Scripts\python.exe -m agi_style_forex_bot_mt5.cli --mode export-history --symbols EURUSD,GBPUSD,USDJPY --timeframes M5,M15,H1 --bars 50000 --output-dir data\historical
```

2. Especificacion de instrumentos. Crea la carpeta `data\runtime` y dentro
   `symbol_map.json` con el nombre exacto de cada simbolo en tu broker, por
   ejemplo `{"EURUSD": "EURUSD", "GBPUSD": "GBPUSD", "USDJPY": "USDJPY"}`
   (guardalo en UTF-8), y ejecuta:

```powershell
New-Item -ItemType Directory -Force data\runtime | Out-Null
.\.venv\Scripts\python.exe -m agi_style_forex_bot_mt5.cli --mode build-instrument-registry --broker-symbol-map data\runtime\symbol_map.json --instrument-registry-output data\runtime\instrument_registry.json
```

3. Comisiones y swap: anotalos a mano desde "Especificacion" del simbolo en MT5,
   con fecha y fuente (el snapshot no incluye swap).
4. La observacion forward-shadow de al menos dos semanas o 200 operaciones de
   papel (lo que tarde mas), con sus carpetas `data\sqlite` y `data\logs`.

Antes de compartir cualquier archivo, comprueba que no contiene tu numero de
cuenta ni nombres de servidor.

## 9. EA nativo y harness matematico (opcional)

Requieren PowerShell 7 y MetaTrader 5 instalado en `C:\Program Files\MetaTrader 5`
(o `-InstallDirectory`). Compilan en una carpeta temporal y no instalan nada en
el terminal:

```powershell
pwsh -NoProfile -File .\scripts\compile_native_observer.ps1
pwsh -NoProfile -File .\scripts\run_native_math_harness.ps1
```

El segundo inicia una copia portable del terminal en modo matematico del
Strategy Tester, sin cuenta. Detalle en `docs/testing/native-math-harness.md`.

## Codigos de salida

| Codigo | Significado |
| --- | --- |
| 0 | Completado; el JSON de salida tiene el detalle. |
| 2 | Argumentos invalidos. |
| 3 | MT5 no conectado (y, en forward-shadow, ningun ciclo completado). |
| 4 | forward-shadow: ciclo de papel bloqueado; requiere revision. |

## Que falta para poder operar

Nada de esta guia habilita operaciones. Una version ejecutable en demo
necesita: una estrategia que supere el Strategy Promotion Gate acumulativo
(`PROJECT_SPEC.md` seccion 12.1) con datos no inspeccionados, la evidencia
forward de la seccion 8, una revision especifica de ejecucion y una nueva
decision de arquitectura. La cuenta real queda fuera del alcance del proyecto.
