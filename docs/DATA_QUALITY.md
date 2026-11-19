# Data quality and provenance

Snapshot quality is checked in three independent areas. These cover record structure, source evidence, and repository coverage. The report is written to `datasets/metadata/quality-report.json` on the data branch and included in each daily release.

## Structural checks

The collector checks:

- Uniqueness of `(product, draw_id)` and prize-row keys.
- Required columns and valid JSON.
- Draw IDs, dates, number ranges, counts, and product-specific uniqueness rules.
- Prize rows linked to an existing draw.
- Draw and prize statuses against known enum values.
- File sizes against publishing limits.

## Provenance

Each row retains `source_url`, `fetched_at`, and source attributes. `data_source` distinguishes official, secondary, and community sources. `source_history` records previous observations before a record is updated from a higher-priority source.

`draw_status` does not indicate whether a source is official. A draw may change from `confirmed` to `not_confirmed`, or back, only when supported by appropriate official evidence.

## Coverage and gaps

The quality report records row counts, date ranges, draw-ID ranges, confirmation status, sources, prize counts, and candidate gaps. A candidate gap is a signal for further collection. It is never converted into an invented record.

## Validation commands

Download the `datasets` branch or extract a release before running these commands against the snapshot directory:

```powershell
vietlott-repository-data validate --source-dir datasets
vietlott-repository-data audit --source-dir datasets
```

The workflow also compares reports from before and after an update to detect sudden drops in valid rows, official-source coverage, or secondary-source coverage. Warnings are saved as run artifacts so they can be reviewed later.
