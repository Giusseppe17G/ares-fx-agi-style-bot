# Diagnostico de secuencias preservadas

Codigo: `496140ec26923c48ec9e5f9a485e87bf89e773bc`, checkout limpio al ejecutar.
Hash fuentes/ scripts del manifest:
`0c57bef42f9007932f5a932967b644e63283a690685761f249beb0912bee8fa5`.
Suite previa: 2101 tests pasaron. Los logs de pytest conservan resultados;
en el log fallido inicial solo se quitaron espacios al final de linea para
permitir `git diff --check`.

Ejecutado desde un directorio externo usando `--source-root` absoluto:

```powershell
py -3.14 -B scripts/replay_sequence_diagnostics.py --source-root <checkout-496140e> --diagnostic-dir <checkout-496140e>/docs/testing/evidence/2026-10-05-shared-pipeline/diagnostic-7abf90e --output-dir <directorio-nuevo> --seed 82 --iterations 2000
```

El output temporal se copio aqui despues de terminar. Los reports_created
conservan sus rutas originales del run; cada directorio contiene esos mismos
archivos. Los manifests de los seis reportes indican commit exacto y
git_dirty=false. Se verificaron los tres hashes CSV contra las entradas
preservadas antes de copiar.

| Simbolo | Trades | P(DD max >= 30%) | Retorno p05 | Stress |
| --- | ---: | ---: | ---: | --- |
| EURUSD | 173 | 9.25% | -30.0055% | REJECTED |
| GBPUSD | 256 | 77.25% | -62.6775% | REJECTED |
| USDJPY | 215 | 43.15% | -45.7520% | REJECTED |

Capital inicial 10000 por simbolo; bootstrap IID, moneda y lotes fijos,
sin riesgo de portfolio, resizing ni costes nuevos. El evento DD30 no es
insolvencia ni estimacion calibrada del riesgo futuro del bot. No se suman
estos resultados como portfolio. La clasificacion legacy WATCHLIST de EURUSD
es diagnostica y no acredita retorno positivo ni promocion.

Datos ya inspeccionados de desarrollo, costes ilustrativos, metadata supuesta
y spreads de procedencia no verificada. Se eliminan columnas de metadata no
consumidas de manera declarada; no se evalua su repr Python ni se alteran datos
economicos. Se preserva el hash CSV completo. Los 20 escenarios aproximados
de stress por simbolo no incluyen los cuatro NOT_MODELED operativos.

Ningun reporte autoriza ejecucion o acredita ventaja estadistica OOS.
