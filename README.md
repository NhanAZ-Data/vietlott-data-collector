# Vietlott Data Collector

`vietlott-data-collector` is a Python tool for collecting, normalizing, and validating Vietlott draw data. CSV snapshots are stored on a dedicated data branch and released daily for applications and research.

## Supported products

Supported products include Mega 6/45 (`mega645`), Power 6/55 (`power655`), Lotto 5/35 (`lotto535`), Max 3D (`max3d`), Max 3D Pro (`max3dpro`), Max 4D (`max4d`), Keno (`keno`), and Bingo18 (`bingo18`).

Each record retains draw results, prize data, confirmation status, and source provenance. Every snapshot includes CSV files, quality metadata, and a hash manifest so users can identify and verify a data version.

## Installation

Python 3.11 or newer is required.

```powershell
git clone https://github.com/NhanAZ-Data/vietlott-data-collector.git
cd vietlott-data-collector
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e '.[parquet]'
```

The optional `parquet` extra installs PyArrow for reading and writing Parquet files. For CSV-only use, install the package with `python -m pip install -e .`.

## Using the collector

List supported products:

```powershell
vietlott-collector products
```

Collect recent draws into a `data/` directory as CSV:

```powershell
vietlott-collector collect `
  --products keno bingo18 `
  --output-dir data `
  --format csv `
  --contact-email you@example.com
```

Continue collecting historical data for all products:

```powershell
vietlott-collector collect --products all --backfill --output-dir data --format csv --contact-email you@example.com
```

Validate the working dataset:

```powershell
vietlott-collector validate --output-dir data --format csv
```

Replace `csv` with `parquet` if you installed the `parquet` extra. Replace `you@example.com` with a contact address that the collector can include in its HTTP User-Agent.

## Downloading released snapshots

Download the latest snapshot from the [`datasets` branch](https://github.com/NhanAZ-Data/vietlott-data-collector/tree/datasets), or choose a date from the [Releases page](https://github.com/NhanAZ-Data/vietlott-data-collector/releases). The data branch advances when new draws or official corrections are collected. A `data-YYYY-MM-DD` release tag identifies the fixed snapshot published for that day. The exact daily release series begins on 2026-06-14.

For a daily historical series from 2017, use the [`reconstructed-datasets` branch](https://github.com/NhanAZ-Data/vietlott-data-collector/tree/reconstructed-datasets) and its [snapshot index](https://github.com/NhanAZ-Data/vietlott-data-collector/blob/reconstructed-datasets/snapshot-index.json). Each `reconstructed-YYYY-MM-DD` tag filters currently available records to `draw_date` values on or before the tag date. These are retrospective reconstructions, not snapshots of what Vietlott or the collector knew on that date. They preserve the source records' `fetched_at` values and provenance, which may postdate the tag. The available archive does not contain a complete observation-time history from 2017.

Clone the data branch by itself:

```powershell
git clone --branch datasets --single-branch --depth 1 https://github.com/NhanAZ-Data/vietlott-data-collector.git vietlott-datasets
```

The downloaded `datasets/` directory contains these main files:

| Path | Contents |
| --- | --- |
| `datasets/draws/<product>/YYYY-MM.csv` | Keno and Bingo18 draws partitioned by month |
| `datasets/draws/<product>/all.csv` | Draws for other products |
| `datasets/prizes/<product>/all.csv` | Prize records |
| `datasets/prize_rules.csv` | Normalized prize rules |
| `datasets/exclusions.csv` | Source-backed draw exclusions |
| `datasets/metadata/dataset-summary.json` | Row counts, products, and date ranges |
| `datasets/metadata/quality-report.json` | Data structure and quality checks |
| `datasets/metadata/snapshot-manifest.json` | File hashes and sizes |

Preserve `draw_status`, `validation_status`, and provenance fields when transforming data. The collector does not invent draws or results from missing draw IDs or scheduled dates.

Hydrate a snapshot into a working dataset:

```powershell
vietlott-repository-data hydrate --source-dir datasets --destination-dir data
```

After updating the data, publish and validate a new snapshot:

```powershell
vietlott-repository-data publish --source-dir data --destination-dir datasets
vietlott-repository-data validate --source-dir datasets
vietlott-repository-data audit --source-dir datasets
```

## Automated updates

GitHub Actions runs the collector from `main`, updates the `datasets` branch, and publishes a daily snapshot at 00:30 ICT (UTC+7). Keno and Bingo18 are checked frequently. Mega 6/45, Power 6/55, Lotto 5/35, Max 3D, and Max 3D Pro are checked on a schedule. Max 4D remains in historical snapshots and is not part of the automated schedule.

Each run restores the working dataset from a snapshot, collects and reconciles records, applies source-backed exclusions, and checks data quality. The workflow updates `datasets` only when a valid snapshot changes. The nightly release is created only after the final daily collection succeeds. Schedules determine when to check sources. They do not cause the collector to invent draws before Vietlott publishes them.

## Documentation

- [Data collection and sources](docs/DATA_COLLECTION.md)
- [Data dictionary](docs/DATA_DICTIONARY.md)
- [Data quality and provenance](docs/DATA_QUALITY.md)
- [Automated updates](docs/AUTOMATED_UPDATES.md)
- [Architecture](docs/ARCHITECTURE.md)
- [Source survey](docs/SOURCE_SURVEY.md)

## Sources and license

The collector prioritizes public results from [Vietlott](https://vietlott.vn/vi/trung-thuong/ket-qua-trung-thuong/). Snapshots retain source information and confirmation status so users can assess records before using them.

This project is not affiliated with or endorsed by Vietlott. The source code is released under the MIT License. Source data remains subject to the rights and terms of its respective owners.
