from __future__ import annotations

import os
import subprocess
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from scripts import backfill_daily_snapshots as backfill
from scripts.publish_dataset_release import snapshot_date

LOCAL_TZ = ZoneInfo("Asia/Ho_Chi_Minh")


def test_snapshot_cutoff_uses_end_of_day_in_vietnam() -> None:
    cutoff = datetime.fromtimestamp(backfill.cutoff_timestamp(date(2026, 11, 19)), LOCAL_TZ)

    assert cutoff.isoformat() == "2026-11-19T23:59:59+07:00"


def test_nightly_default_releases_the_previous_vietnamese_date() -> None:
    now = datetime(2026, 11, 20, 0, 30, tzinfo=LOCAL_TZ)

    assert snapshot_date(None, now) == date(2026, 11, 19)


def test_backfill_reconstructs_and_validates_each_daily_snapshot(tmp_path, monkeypatch) -> None:
    repository = tmp_path / "repo"
    repository.mkdir()
    _run(repository, "init", "--initial-branch=main")
    _run(repository, "config", "user.name", "Snapshot Test")
    _run(repository, "config", "user.email", "snapshot@example.test")

    _write_valid_dataset(repository)
    (repository / "datasets" / "metadata" / "snapshot-manifest.json").unlink()
    _run(repository, "add", "datasets")
    environment = os.environ.copy()
    environment["GIT_AUTHOR_DATE"] = "2026-06-14T16:00:00+07:00"
    environment["GIT_COMMITTER_DATE"] = "2026-06-14T16:00:00+07:00"
    subprocess.run(
        ["git", "-c", "commit.gpgsign=false", "commit", "-m", "data: initial snapshot"],
        cwd=repository,
        env=environment,
        check=True,
        capture_output=True,
        text=True,
    )

    monkeypatch.setattr(backfill, "ROOT", repository)
    snapshots = backfill.build_plan(
        "main",
        date(2026, 6, 14),
        date(2026, 6, 15),
    )

    assert [snapshot.snapshot_date for snapshot in snapshots] == [
        date(2026, 6, 14),
        date(2026, 6, 15),
    ]
    assert snapshots[0].validation["valid"] is True
    assert snapshots[0].metadata_regenerated is True
    assert snapshots[0].tree != snapshots[0].source_tree
    assert snapshots[1].source_commit == snapshots[0].source_commit
    assert snapshots[1].unchanged_from_previous_day is True
    assert snapshots[1].tree == snapshots[0].tree

    report = backfill.report_dict("main", snapshots)
    restored = backfill.snapshots_from_report(report, "main")
    assert [(item.snapshot_date, item.tree) for item in restored] == [
        (item.snapshot_date, item.tree) for item in snapshots
    ]
    assert restored[0].validation["valid"] is True
    assert restored[0].metadata_regenerated is True
    generated_commits = backfill.create_snapshot_commits(restored)
    assert len(generated_commits) == 2
    assert _run(repository, "ls-tree", "--name-only", generated_commits[0][1]).splitlines() == [
        "README.md",
        "datasets",
    ]


def _write_valid_dataset(repository: Path) -> None:
    from vietlott_collector.models import DrawRecord, PrizeRecord
    from vietlott_collector.repository_data import publish_repository_data
    from vietlott_collector.storage import SqliteDatasetStore

    data_dir = repository / "working-data"
    store = SqliteDatasetStore(data_dir)
    try:
        store.upsert(
            [
                DrawRecord(
                    product="mega645",
                    draw_id="00001",
                    draw_date=date(2026, 6, 14),
                    result={"numbers": [1, 2, 3, 4, 5, 6], "special_numbers": []},
                    source_url="https://vietlott.vn/example?id=00001",
                    prize_status="complete",
                    validation_status="valid",
                )
            ],
            [
                PrizeRecord(
                    product="mega645",
                    draw_id="00001",
                    game_variant="Mega 6/45",
                    prize_tier="Jackpot",
                    winning_rule="6 numbers",
                    winner_count=0,
                    prize_value_vnd=12_000_000_000,
                    details={},
                    source_url="https://vietlott.vn/example?id=00001",
                )
            ],
        )
        store.export_csv()
    finally:
        store.close()
    publish_repository_data(data_dir, repository / "datasets")


def _run(repository: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=repository,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()
