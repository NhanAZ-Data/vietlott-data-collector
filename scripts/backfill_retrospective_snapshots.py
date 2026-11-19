from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import os
import re
import subprocess
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from vietlott_collector.repository_data import validate_repository_data  # noqa: E402
from vietlott_collector.storage import DRAW_COLUMNS, PRIZE_COLUMNS  # noqa: E402

TAG_PREFIX = "reconstructed"
HIGH_FREQUENCY_PRODUCTS = {"keno", "bingo18"}
BOT_NAME = "Vietlott Snapshot Reconstruction"
BOT_EMAIL = "41898282+github-actions[bot]@users.noreply.github.com"
RECONSTRUCTION_README = """# Snapshot Vietlott tái dựng hồi cứu

Nhánh này chứa các snapshot hằng ngày được tái dựng hồi cứu, không phải bản sao lịch sử
cho biết dữ liệu đã được biết vào từng ngày. Tag `reconstructed-YYYY-MM-DD` gồm các dòng
hiện có với `draw_date` không muộn hơn ngày trong tag.

Ngày trong tag là mốc lọc theo ngày quay. Bản ghi giữ nguyên `fetched_at` và provenance
hiện có. Nguồn này không cho biết thời điểm dữ liệu được công bố lần đầu, các sửa đổi về
sau hoặc lúc collector biết đến bản ghi.

[`snapshot-index.json`](https://github.com/NhanAZ-Data/vietlott-data-collector/blob/reconstructed-datasets/snapshot-index.json)
liệt kê các tag hằng ngày và liên kết tải archive. Snapshot hằng ngày được ghi nhận tại
thời điểm phát hành riêng bằng tag `data-YYYY-MM-DD`, bắt đầu từ 2026-06-14.
"""


@dataclass
class TreeNode:
    files: dict[str, str] = field(default_factory=dict)
    directories: dict[str, TreeNode] = field(default_factory=dict)
    object_id: str | None = None
    dirty: bool = True


class GitTreeBuilder:
    def __init__(self) -> None:
        self.root = TreeNode()

    def set_file(self, relative_path: str, object_id: str) -> None:
        self._set_entry(relative_path, object_id, is_tree=False)

    def set_tree(self, relative_path: str, object_id: str) -> None:
        self._set_entry(relative_path, object_id, is_tree=True)

    def _set_entry(self, relative_path: str, object_id: str, *, is_tree: bool) -> None:
        parts = relative_path.split("/")
        node = self.root
        ancestors = [node]
        for part in parts[:-1]:
            node = node.directories.setdefault(part, TreeNode())
            ancestors.append(node)
        name = parts[-1]
        if is_tree:
            current = node.directories.get(name)
            if current and not current.dirty and current.object_id == object_id:
                return
            node.directories[name] = TreeNode(object_id=object_id, dirty=False)
        else:
            if node.files.get(name) == object_id:
                return
            node.files[name] = object_id
        node.dirty = True
        node.object_id = None
        for ancestor in ancestors:
            ancestor.dirty = True
            ancestor.object_id = None

    def build(self, git: Git) -> str:
        return self._build_node(self.root, git)

    def _build_node(self, node: TreeNode, git: Git) -> str:
        if not node.dirty and node.object_id:
            return node.object_id
        entries: list[str] = []
        for name, object_id in node.files.items():
            entries.append(f"100644 blob {object_id}\t{name}\n")
        for name, child in node.directories.items():
            child_id = self._build_node(child, git)
            entries.append(f"040000 tree {child_id}\t{name}\n")
        node.object_id = git("mktree", input_text="".join(sorted(entries)))
        node.dirty = False
        return node.object_id


class Git:
    def __init__(self, repository: Path) -> None:
        self.repository = repository

    def __call__(
        self,
        *args: str,
        input_text: str | None = None,
        input_bytes: bytes | None = None,
        check: bool = True,
    ) -> str:
        if input_text is not None and input_bytes is not None:
            raise ValueError("Pass either input_text or input_bytes")
        payload = input_bytes
        if input_text is not None:
            payload = input_text.encode("utf-8")
        result = subprocess.run(
            ["git", *args],
            cwd=self.repository,
            input=payload,
            capture_output=True,
            check=False,
        )
        if check and result.returncode != 0:
            stderr = result.stderr.decode("utf-8", errors="replace").strip()
            stdout = result.stdout.decode("utf-8", errors="replace").strip()
            raise RuntimeError(stderr or stdout)
        return result.stdout.decode("utf-8", errors="replace").strip()


def strict_date(value: str) -> date:
    try:
        parsed = date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("Date must use YYYY-MM-DD") from exc
    if parsed.isoformat() != value:
        raise argparse.ArgumentTypeError("Date must use YYYY-MM-DD")
    return parsed


def json_bytes(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode(
        "utf-8"
    )


def csv_bytes(columns: list[str], rows: list[tuple[str, ...]]) -> bytes:
    output = io.StringIO(newline="")
    writer = csv.writer(output, lineterminator="\n")
    writer.writerow(columns)
    writer.writerows(rows)
    return output.getvalue().encode("utf-8")


def manifest_entry(content: bytes, row_count: int | None = None) -> dict[str, object]:
    entry: dict[str, object] = {
        "bytes": len(content),
        "sha256": hashlib.sha256(content).hexdigest(),
    }
    if row_count is not None:
        entry["data_rows"] = row_count
    return entry


@dataclass
class SourceRows:
    draws_by_date: dict[date, list[tuple[str, ...]]]
    prizes_by_draw: dict[tuple[str, str], list[tuple[str, ...]]]
    exclusions_by_date: dict[date, list[tuple[str, ...]]]
    prize_rules: bytes
    source_summary: dict[str, Any]
    source_manifest: dict[str, Any]


def read_source(source_dir: Path) -> SourceRows:
    report = validate_repository_data(source_dir)
    if not report.get("valid"):
        errors = "; ".join(str(error) for error in report.get("errors", []))
        raise RuntimeError(f"Source dataset is invalid: {errors}")

    draws_by_date: dict[date, list[tuple[str, ...]]] = defaultdict(list)
    draw_dates: dict[tuple[str, str], date] = {}
    for path in sorted((source_dir / "draws").glob("*/*.csv")):
        with path.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            if reader.fieldnames != DRAW_COLUMNS:
                raise RuntimeError(f"Unexpected columns in {path}")
            for row in reader:
                product = row["product"]
                if not re.fullmatch(r"[a-z0-9_-]+", product):
                    raise RuntimeError(f"Unsafe product name in source data: {product!r}")
                draw_date = strict_date(row["draw_date"])
                key = (product, row["draw_id"])
                draw_dates[key] = draw_date
                draws_by_date[draw_date].append(tuple(row[column] or "" for column in DRAW_COLUMNS))

    prizes_by_draw: dict[tuple[str, str], list[tuple[str, ...]]] = defaultdict(list)
    for path in sorted((source_dir / "prizes").glob("*/*.csv")):
        with path.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            if reader.fieldnames != PRIZE_COLUMNS:
                raise RuntimeError(f"Unexpected columns in {path}")
            for row in reader:
                key = (row["product"], row["draw_id"])
                if key not in draw_dates:
                    raise RuntimeError(f"Orphan prize row in source data: {key}")
                prizes_by_draw[key].append(
                    tuple(row[column] or "" for column in PRIZE_COLUMNS)
                )

    exclusion_columns = [
        "product",
        "draw_id",
        "draw_status",
        "effective_date",
        "reason",
        "source_url",
    ]
    exclusions_by_date: dict[date, list[tuple[str, ...]]] = defaultdict(list)
    exclusions_path = source_dir / "exclusions.csv"
    with exclusions_path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames != exclusion_columns:
            raise RuntimeError("Unexpected columns in exclusions.csv")
        for row in reader:
            effective_date = strict_date(row["effective_date"])
            exclusions_by_date[effective_date].append(
                tuple(row[column] or "" for column in exclusion_columns)
            )

    summary = json.loads((source_dir / "metadata" / "dataset-summary.json").read_text(encoding="utf-8"))
    manifest = json.loads(
        (source_dir / "metadata" / "snapshot-manifest.json").read_text(encoding="utf-8")
    )
    rules_path = source_dir / "prize_rules.csv"
    return SourceRows(
        draws_by_date=dict(draws_by_date),
        prizes_by_draw=dict(prizes_by_draw),
        exclusions_by_date=dict(exclusions_by_date),
        prize_rules=rules_path.read_bytes().replace(b"\r\n", b"\n").replace(b"\r", b"\n"),
        source_summary=summary,
        source_manifest=manifest,
    )


def numeric_extreme(old: str | None, new: str, operation) -> str:
    if old is None:
        return new
    if old.isdigit() and new.isdigit():
        width = max(len(old), len(new))
        return str(operation(int(old), int(new))).zfill(width)
    return operation(old, new)


class SnapshotBuilder:
    def __init__(
        self,
        git: Git,
        source: SourceRows,
        source_commit: str,
        source_tag: str,
        generated_at: str,
    ) -> None:
        self.git = git
        self.source = source
        self.source_commit = source_commit
        self.source_tag = source_tag
        self.generated_at = generated_at
        self.tree = GitTreeBuilder()
        self.file_entries: dict[str, dict[str, object]] = {}
        self.partition_rows: dict[str, list[tuple[str, ...]]] = defaultdict(list)
        self.draw_counts: Counter[str] = Counter()
        self.draw_statuses: Counter[str] = Counter()
        self.product_stats: dict[str, dict[str, object]] = {}
        self.latest_fetched_at = ""
        self.total_draws = 0
        self.total_results = 0
        self.total_prizes = 0
        self.prize_counts: Counter[str] = Counter()
        self.draws_with_prizes: set[tuple[str, str]] = set()
        self.included_exclusions: list[tuple[str, ...]] = []
        self.index: list[dict[str, object]] = []
        self.previous_tree: str | None = None
        self.previous_commit: str | None = None
        self.commit_parent: str | None = None
        self._set_static_files()

    def _add_file(self, relative_path: str, content: bytes, rows: int | None = None) -> str:
        object_id = self.git("hash-object", "-w", "--stdin", input_bytes=content)
        self.tree.set_file(relative_path, object_id)
        self.file_entries[relative_path] = manifest_entry(content, rows)
        return object_id

    def _set_static_files(self) -> None:
        self._add_file("prize_rules.csv", self.source.prize_rules)
        self._add_file(
            "exclusions.csv",
            csv_bytes(
                ["product", "draw_id", "draw_status", "effective_date", "reason", "source_url"],
                [],
            ),
            0,
        )
        report = {
            "schema_version": 1,
            "snapshot_kind": "retrospective_reconstruction",
            "tag_prefix": f"{TAG_PREFIX}-YYYY-MM-DD",
            "source_snapshot_tag": self.source_tag,
            "source_snapshot_commit": self.source_commit,
            "source_dataset_updated_at": self.source.source_summary.get("dataset_updated_at"),
            "generated_at_utc": self.generated_at,
            "cutoff_rule": "Include the latest canonical draw rows with draw_date <= the date in the tag.",
            "prize_rule": "Include prize rows belonging to included (product, draw_id) pairs.",
            "exclusion_rule": "Include exclusions whose effective_date is on or before the tag date.",
            "historical_as_known": False,
            "limitations": [
                "This is a retrospective reconstruction, not a record of what was known on the tag date.",
                "Rows retain current values and may include later corrections or discoveries.",
                "The current prize rules are reused because dated historical rule versions are unavailable.",
                "Original fetched_at and provenance fields are preserved and may postdate the tag.",
            ],
        }
        self._add_file("metadata/retrospective-reconstruction.json", json_bytes(report))

    def add_draw(self, row: tuple[str, ...], changed_paths: set[str]) -> None:
        product = row[0]
        draw_id = row[1]
        draw_date = row[2]
        key = (product, draw_id)
        partition = draw_date[:7] if product in HIGH_FREQUENCY_PRODUCTS else "all"
        path = f"draws/{product}/{partition}.csv"
        self.partition_rows[path].append(row)
        changed_paths.add(path)
        self.total_draws += 1
        if json.loads(row[4]):
            self.total_results += 1
        self.draw_counts[product] += 1
        self.draw_statuses[row[3] or "confirmed"] += 1
        self.latest_fetched_at = max(self.latest_fetched_at, row[11])
        stats = self.product_stats.setdefault(
            product,
            {
                "rows": 0,
                "first_date": draw_date,
                "last_date": draw_date,
                "min_id": draw_id,
                "max_id": draw_id,
                "confirmed_rows": 0,
                "not_confirmed_rows": 0,
            },
        )
        stats["rows"] = int(stats["rows"]) + 1
        stats["first_date"] = min(str(stats["first_date"]), draw_date)
        stats["last_date"] = max(str(stats["last_date"]), draw_date)
        stats["min_id"] = numeric_extreme(str(stats["min_id"]), draw_id, min)
        stats["max_id"] = numeric_extreme(str(stats["max_id"]), draw_id, max)
        status_key = f"{row[3] or 'confirmed'}_rows"
        if status_key in stats:
            stats[status_key] = int(stats[status_key]) + 1
        prize_rows = self.source.prizes_by_draw.get(key, [])
        if prize_rows:
            prize_path = f"prizes/{product}/all.csv"
            self.partition_rows[prize_path].extend(prize_rows)
            changed_paths.add(prize_path)
            self.total_prizes += len(prize_rows)
            self.prize_counts[product] += len(prize_rows)
            self.draws_with_prizes.add(key)

    def add_exclusions(self, rows: list[tuple[str, ...]]) -> bool:
        if not rows:
            return False
        self.included_exclusions.extend(rows)
        self.included_exclusions.sort(key=lambda row: (row[3], row[0], row[1]))
        return True

    def refresh_changed_files(self, changed_paths: set[str], exclusions_changed: bool) -> None:
        for path in sorted(changed_paths):
            rows = self.partition_rows[path]
            if path.startswith("prizes/"):
                rows.sort(key=lambda row: (row[1], row[2], row[3], row[4] or "", row[5] or ""))
                columns = PRIZE_COLUMNS
            else:
                columns = DRAW_COLUMNS
            self._add_file(path, csv_bytes(columns, rows), len(rows))
        if exclusions_changed:
            self._add_file(
                "exclusions.csv",
                csv_bytes(
                    ["product", "draw_id", "draw_status", "effective_date", "reason", "source_url"],
                    self.included_exclusions,
                ),
                len(self.included_exclusions),
            )

    def summary(self) -> dict[str, object]:
        return {
            "draw_rows": self.total_draws,
            "confirmed_rows": self.draw_statuses["confirmed"],
            "not_confirmed_rows": self.draw_statuses["not_confirmed"],
            "dataset_updated_at": self.latest_fetched_at or None,
            "products": dict(sorted(self.product_stats.items())),
            "prize_rows": self.total_prizes,
            "schema_version": 1,
            "storage_layout": {
                "high_frequency": "draws/<product>/YYYY-MM.csv",
                "other_products": "draws/<product>/all.csv",
                "prizes": "prizes/<product>/all.csv",
            },
        }

    def quality_report(self, summary: dict[str, object]) -> dict[str, object]:
        return {
            "schema_version": 1,
            "report_version": "retrospective-reconstruction-v1",
            "generated_from_dataset_at": self.source.source_summary.get("dataset_updated_at"),
            "grain": "one canonical row per (product, draw_id)",
            "totals": {
                "draw_rows": self.total_draws,
                "result_rows": self.total_results,
                "prize_rows": self.total_prizes,
                "draws_with_prizes": len(self.draws_with_prizes),
                "duplicate_draw_keys": 0,
            },
            "products": {
                product: {
                    "draw_rows": stats["rows"],
                    "prize_rows": self.prize_counts[product],
                    "first_date": stats["first_date"],
                    "last_date": stats["last_date"],
                }
                for product, stats in sorted(self.product_stats.items())
            },
            "reconstruction": {
                "method": "Filter the validated source snapshot by draw_date and effective_date.",
                "full_aggregate_audit_recomputed": False,
                "source_snapshot_tag": self.source_tag,
                "source_snapshot_commit": self.source_commit,
                "source_quality_report_sha256": self.source.source_manifest.get("files", {})
                .get("metadata/quality-report.json", {})
                .get("sha256"),
            },
            "limitations": [
                "This report verifies reconstructed row counts, not historical knowledge-time quality.",
                "Per-row validation_status, draw_status, fetched_at and provenance are retained.",
            ],
        }

    def manifest(self, summary: dict[str, object]) -> dict[str, object]:
        products = summary.get("products", {})
        date_range = {
            "first": min(
                (str(item["first_date"]) for item in products.values()),
                default=None,
            ),
            "last": max(
                (str(item["last_date"]) for item in products.values()),
                default=None,
            ),
        }
        return {
            "schema_version": 1,
            "snapshot_at": summary.get("dataset_updated_at"),
            "dataset_rows": {"draws": self.total_draws, "prizes": self.total_prizes},
            "date_range": date_range,
            "parser_version": self.source.source_manifest.get("parser_version"),
            "methodology_versions": self.source.source_manifest.get("methodology_versions", {}),
            "repository_commit": self.source_commit,
            "files": dict(sorted(self.file_entries.items())),
        }

    def build_day(self, snapshot_date: date, commit_env: dict[str, str]) -> dict[str, object]:
        changed_paths: set[str] = set()
        exclusions_changed = False
        for draw_date in sorted(self.source.draws_by_date):
            if draw_date <= snapshot_date:
                rows = self.source.draws_by_date.pop(draw_date)
                for row in sorted(rows, key=lambda item: (item[0], item[1])):
                    self.add_draw(row, changed_paths)
            else:
                break

        for effective_date in sorted(self.source.exclusions_by_date):
            if effective_date <= snapshot_date:
                rows = self.source.exclusions_by_date.pop(effective_date)
                exclusions_changed = self.add_exclusions(rows) or exclusions_changed
            else:
                break

        self.refresh_changed_files(changed_paths, exclusions_changed)

        summary = self.summary()
        summary_bytes = json_bytes(summary)
        self._add_file("metadata/dataset-summary.json", summary_bytes)

        quality_bytes = json_bytes(self.quality_report(summary))
        self._add_file("metadata/quality-report.json", quality_bytes)

        manifest_bytes = json_bytes(self.manifest(summary))
        manifest_id = self.git("hash-object", "-w", "--stdin", input_bytes=manifest_bytes)
        self.tree.set_file("metadata/snapshot-manifest.json", manifest_id)

        dataset_tree = self.tree.build(self.git)
        root_builder = GitTreeBuilder()
        readme_id = self.git("hash-object", "-w", "--stdin", input_text=RECONSTRUCTION_README)
        root_builder.set_file("README.md", readme_id)
        root_builder.set_tree("datasets", dataset_tree)
        root_tree = root_builder.build(self.git)

        if root_tree != self.previous_tree:
            args = ["git", "-c", "commit.gpgsign=false", "commit-tree", root_tree]
            if self.commit_parent:
                args.extend(["-p", self.commit_parent])
            args.extend(
                [
                    "-m",
                    f"reconstruction: snapshot {snapshot_date.isoformat()}",
                    "-m",
                    (
                        f"Cutoff: draw_date <= {snapshot_date.isoformat()}\n"
                        f"Source: {self.source_tag} at {self.source_commit}\n"
                        "This is a retrospective reconstruction, not a historical as-known snapshot."
                    ),
                ]
            )
            result = subprocess.run(
                args,
                cwd=ROOT,
                env=commit_env,
                capture_output=True,
                check=False,
            )
            if result.returncode != 0:
                raise RuntimeError(result.stderr.decode("utf-8", errors="replace").strip())
            self.previous_commit = result.stdout.decode("ascii").strip()
            self.commit_parent = self.previous_commit
            self.previous_tree = root_tree

        tag = f"{TAG_PREFIX}-{snapshot_date.isoformat()}"
        self.index.append(
            {
                "date": snapshot_date.isoformat(),
                "tag": tag,
                "commit": self.previous_commit,
                "draw_rows": self.total_draws,
                "prize_rows": self.total_prizes,
                "last_draw_date": max(
                    (str(stats["last_date"]) for stats in self.product_stats.values()),
                    default=None,
                ),
                "snapshot_kind": "retrospective_reconstruction",
                "historical_as_known": False,
            }
        )
        return {
            "date": snapshot_date.isoformat(),
            "tag": tag,
            "commit": self.previous_commit,
            "tree": root_tree,
            "dataset_tree": dataset_tree,
            "draw_rows": self.total_draws,
            "prize_rows": self.total_prizes,
        }


def parse_repository(remote: str) -> str:
    match = re.search(r"github\.com[:/]([^/]+/[^/.]+?)(?:\.git)?$", remote)
    if not match:
        raise RuntimeError(f"Cannot determine GitHub repository from origin URL: {remote}")
    return match.group(1)


def create_plan(
    source_dir: Path,
    start_date: date,
    end_date: date,
    source_tag: str,
    source_commit: str,
    generated_at: str,
) -> tuple[SnapshotBuilder, list[dict[str, object]]]:
    if start_date > end_date:
        raise ValueError("Start date must be on or before end date")
    source = read_source(source_dir)
    builder = SnapshotBuilder(
        Git(ROOT),
        source,
        source_commit,
        source_tag,
        generated_at,
    )
    commit_env = os.environ.copy()
    commit_env.update(
        {
            "GIT_AUTHOR_NAME": BOT_NAME,
            "GIT_AUTHOR_EMAIL": BOT_EMAIL,
            "GIT_AUTHOR_DATE": generated_at,
            "GIT_COMMITTER_NAME": BOT_NAME,
            "GIT_COMMITTER_EMAIL": BOT_EMAIL,
            "GIT_COMMITTER_DATE": generated_at,
        }
    )
    snapshots: list[dict[str, object]] = []
    current = start_date
    total_days = (end_date - start_date).days + 1
    while current <= end_date:
        snapshot = builder.build_day(current, commit_env)
        snapshots.append(snapshot)
        if len(snapshots) % 100 == 0:
            print(
                f"Prepared {len(snapshots)}/{total_days} dates through {current.isoformat()}",
                flush=True,
            )
        current += timedelta(days=1)
    return builder, snapshots


def create_index(
    repository: str,
    source_tag: str,
    source_commit: str,
    generated_at: str,
    snapshots: list[dict[str, object]],
) -> dict[str, object]:
    return {
        "schema_version": 1,
        "snapshot_kind": "retrospective_reconstruction",
        "historical_as_known": False,
        "generated_at_utc": generated_at,
        "source_snapshot": {"tag": source_tag, "commit": source_commit},
        "date_range": {"first": snapshots[0]["date"], "last": snapshots[-1]["date"]},
        "snapshot_count": len(snapshots),
        "method": (
            "For each tag date, include current source rows whose draw_date is on "
            "or before that date."
        ),
        "limitations": [
            "These tags do not show what Vietlott or the collector knew on that date.",
            "Later corrections and delayed discovery remain present in earlier reconstructed snapshots.",
            "Prize rules use the current version because dated historical versions are unavailable.",
        ],
        "snapshots": [
            {
                **snapshot,
                "archive_url": (
                    f"https://github.com/{repository}/archive/refs/tags/{snapshot['tag']}.zip"
                ),
            }
            for snapshot in snapshots
        ],
        "exact_daily_releases": {
            "tag_pattern": "data-YYYY-MM-DD",
            "starts_after_reconstruction": True,
            "url": f"https://github.com/{repository}/releases",
        },
    }


def publish(
    git: Git,
    branch: str,
    release_tag: str,
    snapshots: list[dict[str, object]],
    index: dict[str, object],
) -> None:
    if not snapshots:
        raise RuntimeError("No reconstructed snapshots were generated")
    repository = parse_repository(git("remote", "get-url", "origin"))
    subprocess.run(["gh", "auth", "status"], cwd=ROOT, check=True)
    subprocess.run(["gh", "auth", "setup-git"], cwd=ROOT, check=True)
    tags: dict[str, str] = {str(item["tag"]): str(item["commit"]) for item in snapshots}

    index_bytes = json_bytes(index)
    index_blob = git("hash-object", "-w", "--stdin", input_bytes=index_bytes)
    index_tree_builder = GitTreeBuilder()
    readme_blob = git(
        "hash-object", "-w", "--stdin", input_text=RECONSTRUCTION_README
    )
    index_tree_builder.set_file("README.md", readme_blob)
    final_dataset_tree = snapshots[-1]["dataset_tree"]
    if not isinstance(final_dataset_tree, str):
        raise RuntimeError("Snapshot tree ID is missing")
    index_tree_builder.set_tree("datasets", final_dataset_tree)
    index_tree_builder.set_file("snapshot-index.json", index_blob)
    index_root_tree = index_tree_builder.build(git)

    parent = str(snapshots[-1]["commit"])
    env = os.environ.copy()
    env.update(
        {
            "GIT_AUTHOR_NAME": BOT_NAME,
            "GIT_AUTHOR_EMAIL": BOT_EMAIL,
            "GIT_AUTHOR_DATE": str(index["generated_at_utc"]),
            "GIT_COMMITTER_NAME": BOT_NAME,
            "GIT_COMMITTER_EMAIL": BOT_EMAIL,
            "GIT_COMMITTER_DATE": str(index["generated_at_utc"]),
        }
    )
    result = subprocess.run(
        [
            "git",
            "-c",
            "commit.gpgsign=false",
            "commit-tree",
            index_root_tree,
            "-p",
            parent,
            "-m",
            "index: reconstructed daily snapshots",
        ],
        cwd=ROOT,
        env=env,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.decode("utf-8", errors="replace").strip())
    branch_head = result.stdout.decode("ascii").strip()
    tags[release_tag] = branch_head

    remote = git("ls-remote", "origin", f"refs/heads/{branch}", "refs/tags/reconstructed-*")
    remote_refs = {
        ref: sha
        for sha, ref in (line.split("\t", maxsplit=1) for line in remote.splitlines())
    }
    remote_branch = remote_refs.get(f"refs/heads/{branch}")
    if remote_branch and remote_branch != branch_head:
        raise RuntimeError(
            f"Remote branch {branch} already exists at {remote_branch}, expected {branch_head}"
        )
    for tag, expected in tags.items():
        existing = remote_refs.get(f"refs/tags/{tag}")
        if existing and existing != expected:
            raise RuntimeError(f"Remote tag {tag} points to {existing}, expected {expected}")

    local_branch = git("show-ref", "--verify", f"refs/heads/{branch}", check=False)
    if local_branch:
        local_head = git("rev-parse", f"refs/heads/{branch}")
        if local_head != branch_head:
            raise RuntimeError(f"Local branch {branch} already exists at {local_head}")
    else:
        git("update-ref", f"refs/heads/{branch}", branch_head)

    updates = [f"update refs/tags/{tag} {commit}" for tag, commit in tags.items()]
    if not remote_branch:
        updates.insert(0, f"update refs/heads/{branch} {branch_head}")
    if updates:
        git("update-ref", "--stdin", input_text="start\n" + "\n".join(updates) + "\nprepare\ncommit\n")

    if not remote_branch:
        git("push", "origin", f"refs/heads/{branch}:refs/heads/{branch}")
    missing_tags = [tag for tag in tags if f"refs/tags/{tag}" not in remote_refs]
    for offset in range(0, len(missing_tags), 100):
        batch = missing_tags[offset : offset + 100]
        git(
            "push",
            "origin",
            *[f"refs/tags/{tag}:refs/tags/{tag}" for tag in batch],
        )

    exists = subprocess.run(
        ["gh", "release", "view", release_tag, "--repo", repository],
        cwd=ROOT,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    if exists.returncode != 0:
        notes = (
            f"Daily retrospective snapshots from {snapshots[0]['date']} to {snapshots[-1]['date']}.\n\n"
            "Each `reconstructed-YYYY-MM-DD` tag is downloadable as a GitHub source archive. "
            "The date is a draw-date cutoff, not a claim about what was known on that date.\n\n"
            f"Snapshot index: https://github.com/{repository}/blob/{branch}/snapshot-index.json\n"
            f"Source snapshot: `{index['source_snapshot']['tag']}` at `{index['source_snapshot']['commit']}`"
        )
        subprocess.run(
            [
                "gh",
                "release",
                "create",
                release_tag,
                "--repo",
                repository,
                "--verify-tag",
                "--title",
                "Vietlott retrospective snapshots 2017-2026",
                "--notes",
                notes,
            ],
            cwd=ROOT,
            check=True,
        )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Create clearly labeled retrospective daily Vietlott snapshots."
    )
    parser.add_argument("--source-dir", type=Path, required=True)
    parser.add_argument("--source-tag", default="data-2026-11-18")
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--start-date", type=strict_date, default=date(2017, 1, 1))
    parser.add_argument("--end-date", type=strict_date, required=True)
    parser.add_argument("--branch", default="reconstructed-datasets")
    parser.add_argument("--release-tag", default="reconstructed-history-2017-2026")
    parser.add_argument("--generated-at", help="Stable UTC timestamp for deterministic regeneration.")
    parser.add_argument("--report", type=Path)
    parser.add_argument("--publish", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    generated_at = args.generated_at or datetime.now(UTC).replace(microsecond=0).isoformat()
    _, snapshots = create_plan(
        args.source_dir.resolve(),
        args.start_date,
        args.end_date,
        args.source_tag,
        args.source_commit,
        generated_at,
    )
    repository = parse_repository(Git(ROOT)("remote", "get-url", "origin"))
    index = create_index(repository, args.source_tag, args.source_commit, generated_at, snapshots)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(
            json.dumps(index, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    print(
        f"Prepared {len(snapshots)} retrospective snapshots from "
        f"{snapshots[0]['date']} through {snapshots[-1]['date']} "
        f"on branch {args.branch}.",
        flush=True,
    )
    if args.publish:
        publish(Git(ROOT), args.branch, args.release_tag, snapshots, index)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
