# Data collection and sources

The collector prioritizes Vietlott's public results pages. Each observation is saved with its URL, fetch time, confirmation status, prize status, and source provenance.

## Primary source

- [Mega 6/45](https://vietlott.vn/vi/trung-thuong/ket-qua-trung-thuong/winning-number-645)
- [Power 6/55](https://vietlott.vn/vi/trung-thuong/ket-qua-trung-thuong/winning-number-655)
- [Lotto 5/35](https://vietlott.vn/vi/trung-thuong/ket-qua-trung-thuong/winning-number-535)
- [Max 3D](https://vietlott.vn/vi/trung-thuong/ket-qua-trung-thuong/winning-number-max-3D)
- [Max 3D Pro](https://vietlott.vn/vi/trung-thuong/ket-qua-trung-thuong/winning-number-max-3Dpro)
- [Max 4D](https://vietlott.vn/vi/trung-thuong/ket-qua-trung-thuong/winning-number-max-4d)
- [Keno](https://vietlott.vn/vi/trung-thuong/ket-qua-trung-thuong/winning-number-keno)
- [Bingo18](https://vietlott.vn/vi/trung-thuong/ket-qua-trung-thuong/winning-number-bingo18)

The first page contains recent draws. When needed, the collector reads additional pages through AjaxPro. Detail pages provide prize tables and PDF links. The AjaxPro key is read from the page at runtime and is not hard-coded.

## Secondary sources

When both official HTML and AjaxPro are unavailable, the collector uses product-specific secondary sources: the public [Xổ Số VN Keno API](https://www.xosovnm.net/nguon-api), [Xem Nhanh's Bingo18 draw pages](https://xemnhanh.vn/vietlott/bingo18), or results from [Xổ Số Minh Ngọc](https://xosominhngoc.net.vn/kqxs-vietlott). The parser requires a valid draw ID, date, and result. Records from these sources are marked as pending official verification.

Secondary-source records must include provenance in `attributes_json`, including the source, URL, and verification status. When Vietlott is available again, the collector reads the official source and replaces secondary-source details where appropriate.

## Keno and Bingo18

These high-frequency products have dedicated history collectors. Draw-ID gaps are filled only when an independent observation provides sufficient evidence. Draws officially reported as not issued are recorded in `datasets/exclusions.csv` or retained with `draw_status=not_confirmed`. Results are never inferred from adjacent draw IDs.

The latest snapshot is stored on the `datasets` branch. Each `data-YYYY-MM-DD` release contains the full snapshot published for that day. Retrospective snapshots from 2017 are on `reconstructed-datasets` under `reconstructed-YYYY-MM-DD` tags. Those tags filter current records by draw date and do not represent what the collector knew at the time. See `snapshot-index.json` on the reconstruction branch for the full date range and limitations.

## Update cycle

1. Restore CSV files from `datasets` into SQLite.
2. Read official results and new pages or ranges that need reconciliation.
3. Parse records, validate them, and upsert them by their stable keys.
4. If the official source is unavailable, try the configured secondary source.
5. Apply official exclusions and retain previous source observations.
6. Export CSV files, generate metadata, and validate the snapshot.
7. Publish only when `validate` reports no errors.

## Access limits

The HTTP client uses retries, backoff, jitter, and `Retry-After`. It does not increase request rates to bypass source limits. If the page structure changes unexpectedly, the parser stops and reports an error instead of guessing.
