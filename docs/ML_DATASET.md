# ML Dataset

The ML dataset is built from feature rows and closed-trade labels.

Open paper trades are not used as definitive labels.

## Build

```powershell
$env:PYTHONPATH="src/python"
py -m agi_style_forex_bot_mt5.cli --mode build-ml-dataset --sqlite data\sqlite\forward-shadow.sqlite3 --reports-root data\reports --output-dir data\reports\ml
```

Outputs:

- `data/reports/ml/feature_store.csv`
- `data/reports/ml/feature_store.parquet` when parquet support is available
- `data/reports/ml/labels.csv`
- `data/reports/ml/ml_dataset.csv`
- `data/reports/ml/dataset_manifest.json`

## Features

Features include symbol/session/regime/strategy encodings, score, spread, tick age, technical indicators, broker readiness, recent rejection rate, paper winrate, expectancy and drawdown.

## Labels

Labels include:

- `label_win`
- `label_hit_tp`
- `label_expected_r`
- `label_bad_mae`
- `label_good_mfe`
- `label_hold_quality`

The dataset is split temporally into train, validation and test.

