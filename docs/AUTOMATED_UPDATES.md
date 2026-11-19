# Automated updates

Scheduled workflows are polling schedules. The collector does not create a draw just because a scheduled time has arrived.

## Current schedules

- `update-fast.yml`: Keno and Bingo18 during frequent polling windows.
- `update-scheduled.yml`: Mega 6/45, Power 6/55, Lotto 5/35, Max 3D, and Max 3D Pro around their expected publication windows.
- Max 4D remains historical data and is collected only when requested manually.

Schedules can change. The official source takes precedence over this document.

## One update run

1. Check out `main` for the collector and check out `datasets` in a separate directory.
2. Hydrate the snapshot from `datasets` into the SQLite working store.
3. Run `vietlott-auto-update` for the selected products.
4. If the official source fails, try a configured secondary source.
5. Publish to `datasets`, synchronize the branch, then run `validate`, `audit`, and quality-regression checks.
6. Commit to `datasets` only when a valid snapshot has changed.
7. At 00:30 ICT (UTC+7), run the final daily collection. If it succeeds, create the `data-YYYY-MM-DD` tag and GitHub Release from the validated snapshot.

Run reports are stored in the Actions runner's temporary directory. Persistent data is stored on `datasets` and in published releases.

## Failure handling

- Delayed results: the next run rechecks the recent range.
- Multiple new draws: the collector continues through pages until it reaches known data.
- Cancelled draws or discontinued products: no records are invented.
- Network errors: retries use backoff, jitter, and `Retry-After`.
- Changed HTML: the parser stops with an error for controlled repair.
- One product fails: valid data from other products is retained, then the workflow reports failure.
- The final run for a day fails: valid data remains on `datasets`, but that day's snapshot is not released.
- A release tag already exists: it is never overwritten. A corrected release uses a new tag with an `-r2` suffix.

The repository does not build or deploy a website and does not generate prediction or analysis artifacts.
