# Data dictionary

This document describes the snapshots in `datasets/` and the working data created by the collector. The latest exact snapshot is on the `datasets` branch. Each `data-YYYY-MM-DD` release contains the full snapshot captured for that release date. The schema is designed so users can download, inspect, and reuse the data without relying on parser internals.

## Retrospective snapshots

Each `reconstructed-YYYY-MM-DD` tag on `reconstructed-datasets` filters the current source snapshot to records with `draw_date` on or before the date in the tag. It does not represent what Vietlott or the collector knew on that historical date. Records retain their current values, `fetched_at`, and provenance, so later corrections or discoveries can appear in earlier reconstructed tags. Prize rules use the current version because dated rule versions are unavailable.

The branch's `snapshot-index.json` lists each tag, row counts, and archive links. Read `datasets/metadata/retrospective-reconstruction.json` in an archive for the source, cutoff rule, and limitations. Use `data-YYYY-MM-DD` releases for snapshots captured at their release time.

## Snapshot layout

| Path | Contents |
| --- | --- |
| `datasets/draws/<product>/YYYY-MM.csv` | Keno and Bingo18 draws partitioned by month |
| `datasets/draws/<product>/all.csv` | Draws for other products |
| `datasets/prizes/<product>/all.csv` | Prize rows |
| `datasets/prize_rules.csv` | Normalized prize rules |
| `datasets/exclusions.csv` | Source-backed status exclusions |
| `datasets/metadata/dataset-summary.json` | Row counts, products, and date ranges |
| `datasets/metadata/quality-report.json` | Data quality checks |
| `datasets/metadata/snapshot-manifest.json` | Hashes, sizes, and collector version |

The identity key for a draw is `(product, draw_id)`. Do not merge products just because they share a draw ID.

## Draw table

Columns in `draws` always use this order:

| Column | Meaning |
| --- | --- |
| `product` | Canonical product slug, such as `mega645` or `keno` |
| `draw_id` | Draw identifier, including leading zeroes |
| `draw_date` | ISO date of the published draw |
| `draw_status` | `confirmed` or `not_confirmed` |
| `result_json` | Product-specific normalized result |
| `attributes_json` | Additional attributes and source-observation history |
| `official_pdf_urls_json` | Official PDF URLs found for the draw |
| `source_url` | URL of the saved observation |
| `prize_status` | Prize-data state: `complete`, `rules_available`, `empty`, `not_applicable`, or a transition state |
| `validation_status` | Structural check result: `valid`, `warning`, or `unchecked` |
| `validation_warnings_json` | Warnings that do not remove the record |
| `fetched_at` | UTC time when the data was fetched |

`result_json` is a JSON object. Number games commonly use `numbers` and may include `special_numbers`. Digit games use `digits` or fields documented by the parser. Do not edit JSON by hand without running `validate` again.

## Prize table

The logical key is `(product, draw_id, game_variant, prize_tier, winning_rule, prize_value_vnd)`.

| Column | Meaning |
| --- | --- |
| `product`, `draw_id` | Link back to the draw |
| `game_variant` | Game variant or prize table |
| `prize_tier` | Published prize tier |
| `winning_rule` | Matching condition for the prize |
| `winner_count` | Number of winners, blank when the source does not provide it |
| `prize_value_vnd` | Prize value in VND, blank when the source does not provide it |
| `details_json` | Source columns and table position |
| `source_url`, `fetched_at` | Row provenance |

Blank and zero are different values. The collector does not replace a blank source value with zero.

## Provenance and status

`attributes_json` may contain `data_source`, `official_verification_status`, `secondary_source_url`, `consensus_sources`, `official_list_verified_at`, and `source_history`. These fields record provenance. They do not replace `validation_status`.

- `draw_status=confirmed` means the draw is accepted under the available source evidence.
- `draw_status=not_confirmed` is retained for traceability and is not removed from snapshots.
- `validation_status=valid` means deterministic checks passed for IDs, counts, value ranges, and uniqueness.
- Secondary-source records remain labeled for review. Official sources take precedence when the collector reconciles them.

## Safe use

1. Read `snapshot-manifest.json` and verify hashes when you need to identify an exact file version.
2. Read the CSV columns as strings for `product` and `draw_id` to preserve leading zeroes.
3. Respect `draw_status`, `validation_status`, and provenance instead of inferring status from a draw ID.
4. Run `vietlott-repository-data validate --source-dir datasets` before redistributing a copy.
