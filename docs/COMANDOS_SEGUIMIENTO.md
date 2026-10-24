# Comandos del seguimiento en papel (lista para no olvidar)

Lista corta para copiar y pegar en PowerShell. La explicacion completa esta
en `docs/GUIA_DE_USO.md` (seccion 12); el plan congelado, en
`docs/research/daily-fx-value-forward-v1.md`. Nada de esto envia ordenes: los
mensajes de Telegram describen operaciones en papel.

- Primer dia que cuenta: **2026-10-26**.
- Codigo fijo del seguimiento: commit `a81a4ca03c892d07b6d065c155e7b727bf7371bd`.
- Revisiones anuales (las cifras solo deciden en estas fechas): 2027-10-26,
  2028-10-26, 2029-10-26, 2030-10-26, 2031-10-26, 2032-10-26, 2033-10-26,
  2034-10-26, 2035-10-26 y 2036-10-26.

## 0. Antes de empezar

- [ ] El bot esta instalado (`docs/GUIA_DE_USO.md`, seccion 2) y la
      configuracion esta en `C:\ares-config\bot.ini` con `DEMO_ONLY=True`.
- [ ] MT5 esta abierto con la cuenta **demo**.
- [ ] Los 9 pares estan en la Observacion de mercado: AUDUSD, USDCAD, USDCHF,
      USDDKK, GBPUSD, USDJPY, USDNOK, NZDUSD, USDSEK.

En cada consola nueva, dentro de la carpeta del proyecto:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
$env:PYTHONPATH = "src/python"
```

## 1. Una sola vez

```powershell
# Carpetas y mapa de simbolos (cambia los nombres de la derecha si tu broker usa sufijos, p. ej. USDJPY.r)
New-Item -ItemType Directory -Force data\runtime\forward, data\historical\forward, data\historical\worldbank | Out-Null
[IO.File]::WriteAllText("$PWD\data\runtime\symbol_map_forward.json", '{"AUDUSD": "AUDUSD", "USDCAD": "USDCAD", "USDCHF": "USDCHF", "USDDKK": "USDDKK", "GBPUSD": "GBPUSD", "USDJPY": "USDJPY", "USDNOK": "USDNOK", "NZDUSD": "NZDUSD", "USDSEK": "USDSEK"}')

# Copia fija del codigo del seguimiento (junto a la carpeta del proyecto)
git fetch origin
git worktree add ..\ares-forward-v1 a81a4ca03c892d07b6d065c155e7b727bf7371bd

# Archivo de inflacion fijado (la huella debe ser 182BAA44C536079BEA07BB8700C37C85441C3D7D5F8E6DD68FB92FCB4A7815E8)
git clone -c core.autocrlf=false https://github.com/datasets/cpi.git C:\ares-data\cpi
git -C C:\ares-data\cpi checkout 3750e45064a99b0452deb1423a416e4d5473a58e
Copy-Item C:\ares-data\cpi\data\cpi.csv data\historical\worldbank\cpi.csv
(Get-FileHash data\historical\worldbank\cpi.csv -Algorithm SHA256).Hash

# Inflacion de 2025 en adelante (Banco Mundial; unica llamada a internet)
.\.venv\Scripts\python.exe -m agi_style_forex_bot_mt5.research.daily_fx.forward_inflation fetch-inflation --output "data\historical\worldbank\inflation-$(Get-Date -Format yyyyMMdd).csv"
```

Telegram (opcional; token de `@BotFather` y chat id de tu canal, ver
`docs/GUIA_DE_USO.md` seccion 12, paso 6) y tarea semanal automatica (lunes
10:00; quita `-Telegram` si no usas Telegram):

```powershell
setx TELEGRAM_BOT_TOKEN "<token de tu bot>"
setx TELEGRAM_CHAT_ID "<tu chat id>"
# Cierra la sesion de Windows, vuelve a entrar y ve a la carpeta del proyecto
.\scripts\run_forward_tracking.ps1 -Config C:\ares-config\bot.ini -TestTelegram
.\scripts\install_forward_tracking_task.ps1 -Config C:\ares-config\bot.ini -Telegram
Start-ScheduledTask -TaskName AresForwardTracking
```

- [ ] La huella del `cpi.csv` coincide.
- [ ] `fetch-inflation` termino con codigo 0 y el archivo trae los 10 paises.
- [ ] La primera vez, el snapshot de swap dice `"swap_mode_name": "POINTS"`
      en los 9 simbolos (`data\runtime\forward\swap_snapshot-*.json`; si no,
      avisame).
- [ ] Con Telegram, `-TestTelegram` termino con codigo 0 y el mensaje de
      prueba llego al canal.
- [ ] La prueba de la tarea termino con codigo 0 (mira
      `data\logs\forward`). El mensaje de inicio llega con la primera
      rutina que selle un dia desde el 2026-10-26.

## 2. Cada semana (como minimo una vez cada 4 semanas)

### Opcion A (recomendada): la rutina en un solo comando

La tarea programada la corre sola cada lunes (el lunes cuenta hasta el
viernes; un sabado solo contaria hasta el jueves). Para correrla a mano, con
MT5 abierto y desde la carpeta del proyecto:

```powershell
.\scripts\run_forward_tracking.ps1 -Config C:\ares-config\bot.ini -Telegram
```

- [ ] Codigo 0 (2 = parada, la alerta dice que hacer; 3 = MT5 no
      disponible: abrelo y repite; 4 = un mensaje de Telegram no salio, se
      reintenta la proxima vez).
- [ ] Sin Telegram, lee los mensajes en
      `data\runtime\forward\telegram_messages.txt`.
- [ ] Una vez al mes, mira en `data\runtime\forward\runs` (el `run-*.json`
      mas reciente) `rule.status` y `summary.broker_swap.coverage`.

### Opcion B: a mano, paso a paso

Con MT5 abierto, desde la carpeta del proyecto:

```powershell
# 1) Precios diarios de los 9 pares: la salida debe decir "files_created": 9
.\.venv\Scripts\python.exe -m agi_style_forex_bot_mt5.cli --mode export-history --symbols AUDUSD,USDCAD,USDCHF,USDDKK,GBPUSD,USDJPY,USDNOK,NZDUSD,USDSEK --timeframes D1 --bars 3000 --output-dir data\historical\forward --config C:\ares-config\bot.ini

# 2) Swap real del broker
.\.venv\Scripts\python.exe -m agi_style_forex_bot_mt5.cli --mode capture-swap-snapshot --broker-symbol-map data\runtime\symbol_map_forward.json --swap-snapshot-output "data\runtime\forward\swap_snapshot-$(Get-Date -Format yyyyMMdd-HHmmss).json" --config C:\ares-config\bot.ini

# 3) Seguimiento, desde la copia fija (usa sola la inflacion descargada mas reciente)
$Bot = (Get-Location).Path
$Infl = (Get-ChildItem "$Bot\data\historical\worldbank\inflation-*.csv" | Sort-Object Name | Select-Object -Last 1).FullName
Push-Location ..\ares-forward-v1
$env:PYTHONPATH = "src/python"
& "$Bot\.venv\Scripts\python.exe" -m agi_style_forex_bot_mt5.research.daily_fx.forward_runner run --plan-file docs\research\daily_fx_value_forward_v1\plan.json --prices-dir "$Bot\data\historical\forward" --inflation-base "$Bot\data\historical\worldbank\cpi.csv" --inflation-supplement $Infl --swap-snapshots-dir "$Bot\data\runtime\forward" --ledger "$Bot\data\runtime\forward\value_forward_v1.jsonl"
Pop-Location
```

- [ ] La exportacion dice `"files_created": 9` (si no, repitela antes del paso 3).
- [ ] El seguimiento termino con codigo 0.
- [ ] Mira en la salida `rule.status` (lo normal es `ONGOING`),
      `waiting_for_inputs_on` (debe estar vacio) y
      `summary.broker_swap.coverage` (debe acercarse a 1).

## 3. Cada ano, despues de julio

La rutina de la opcion A descarga sola la inflacion nueva cuando hace falta.
Con la opcion B:

```powershell
.\.venv\Scripts\python.exe -m agi_style_forex_bot_mt5.research.daily_fx.forward_inflation fetch-inflation --output "data\historical\worldbank\inflation-$(Get-Date -Format yyyyMMdd).csv"
```

- [ ] El paso 3 semanal usa solo el archivo mas reciente; si
      `waiting_for_inputs_on` sigue lleno, el Banco Mundial aun no publico el
      ano: repite la descarga unas semanas despues.

## 4. Cada 3 meses y en cada revision anual

- [ ] Copia de seguridad de `data\runtime\forward` (ledger y snapshots) y
      de `data\historical\worldbank`.
- [ ] Enviame `data\runtime\forward\value_forward_v1.jsonl` para guardarlo en
      el repositorio (no tiene datos de tu cuenta).
- [ ] En las revisiones anuales, enviame tambien la salida completa del
      paso 3.

## 5. Si algo falla (codigo 2): no borres nada

| Codigo | Que hacer |
|---|---|
| `PRICES_STALE` | Un par no se exporto: repite la exportacion y vuelve a correr. |
| `PRICES_TOO_SHORT` / `PRICES_MISSING` | Sube `--bars` o anade el par a la Observacion de mercado. |
| `FORWARD_HISTORY_CHANGED` | Tu broker cambio barras antiguas o falta un dato: guarda ledger y exportaciones y avisame. |
| `PLAN_MISMATCH` / `ENGINE_CHANGED` | No estas en la copia fija: vuelve a crearla con el commit de arriba. |
| `INFLATION_BASE_CHANGED` | El `cpi.csv` no es el fijado: repite su copia del paso 1. |
| Codigo 3 en `fetch-inflation` | Sin conexion con el Banco Mundial: reintentalo mas tarde. |
| `EXPORT_INCOMPLETE` (rutina) | MT5 no trajo los 9 pares: revisa la Observacion de mercado y repite. |
| `MT5_UNAVAILABLE` (rutina, codigo 3) | MT5 cerrado o sin sesion: abrelo con la cuenta demo y repite. |
| `ROUTINE_ALREADY_RUNNING` (rutina) | Ya hay otra rutina en marcha: espera a que termine. |
| `WORKTREE_MISSING` (rutina) | Falta la copia fija `..\ares-forward-v1`: vuelve a crearla con el commit de arriba. |
| `REPORT_FAILED` (rutina) | No se pudo escribir el informe: el seguimiento sigue valido; guarda la salida y avisame. |
| `RECORD_MISMATCH` / `TRADES_MISMATCH` (rutina) | El informe no reproduce el registro o el motor: el seguimiento sigue valido, pero no borres nada y avisame. |

## 6. Nunca

- Editar, recortar o borrar el ledger (`value_forward_v1.jsonl`).
- Correr el seguimiento desde `main` en vez de la copia fija.
- Usar otro `cpi.csv` o cambiar a mano los archivos de inflacion ya usados.
- Usar una cuenta real: el seguimiento es solo en papel y un `CONFIRMED` no
  activa nada.
