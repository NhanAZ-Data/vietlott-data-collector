from __future__ import annotations

import argparse
import bisect
import io
import json
import os
import re
import subprocess
import sys
import tarfile
import tempfile
import time
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from datetime import time as daytime
from itertools import pairwise
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

LOCAL_TZ = ZoneInfo("Asia/Ho_Chi_Minh")
BOT_NAME = "Vietlott Data Snapshot Bot"
BOT_EMAIL = "41898282+github-actions[bot]@users.noreply.github.com"
DATA_README = """# Vietlott data snapshots

This branch stores validated snapshots under `datasets/`.

- Use the `datasets` branch for the latest snapshot.
- Use a GitHub Release tagged `data-YYYY-MM-DD` for a fixed daily snapshot.
- Read `datasets/metadata/snapshot-manifest.json` to verify file hashes.

Collector source and usage instructions are in the `main` branch README.
"""


@dataclass(frozen=True)
class DatasetCommit:
    sha: str
    timestamp: int
    tree: str


@dataclass(frozen=True)
class Snapshot:
    snapshot_date: date
    source_commit: str
    source_timestamp: int
    source_tree: str
    tree: str
    unchanged_from_previous_day: bool
    metadata_regenerated: bool
    validation: dict[str, Any]


def git(*args: str, input_text: str | None = None, check: bool = True) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=ROOT,
        input=input_text.encode("utf-8") if input_text is not None else None,
        capture_output=True,
        check=False,
    )
    if check and result.returncode != 0:
        stderr = result.stderr.decode("utf-8", errors="replace").strip()
        stdout = result.stdout.decode("utf-8", errors="replace").strip()
        raise RuntimeError(stderr or stdout)
    return result.stdout.decode("utf-8", errors="replace").strip()


def parse_date(value: str) -> date:
    try:
        parsed = date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("Date must use YYYY-MM-DD") from exc
    if parsed.isoformat() != value:
        raise argparse.ArgumentTypeError("Date must use YYYY-MM-DD")
    return parsed


def latest_complete_local_date(now: datetime | None = None) -> date:
    return (now or datetime.now(LOCAL_TZ)).astimezone(LOCAL_TZ).date() - timedelta(days=1)


def source_dataset_commits(source_ref: str) -> list[DatasetCommit]:
    tip_tree = git("rev-parse", f"{source_ref}:datasets", check=False)
    if not tip_tree:
        raise RuntimeError(
            f"Source ref {source_ref} must still contain datasets/ at its tip. "
            "Run the historical backfill before removing datasets/ from main."
        )
    output = git(
        "log",
        "--first-parent",
        "--reverse",
        "--format=%H%x09%ct",
        source_ref,
        "--",
        "datasets",
    )
    rows = [line.split("\t", maxsplit=1) for line in output.splitlines()]
    tree_output = subprocess.run(
        ["git", "cat-file", "--batch-check=%(objectname) %(objecttype)"],
        cwd=ROOT,
        input="".join(f"{sha}:datasets\n" for sha, _ in rows),
        text=True,
        capture_output=True,
        check=True,
    ).stdout.splitlines()
    commits: list[DatasetCommit] = []
    for (sha, raw_timestamp), tree_line in zip(rows, tree_output, strict=True):
        fields = tree_line.split(maxsplit=1)
        if len(fields) != 2 or fields[1] != "tree":
            continue
        commits.append(DatasetCommit(sha, int(raw_timestamp), fields[0]))

    if not commits:
        raise RuntimeError(f"No dataset snapshots were found in {source_ref}")
    if any(right.timestamp < left.timestamp for left, right in pairwise(commits)):
        raise RuntimeError("Dataset commit timestamps are not monotonic on first-parent history")
    return commits


def cutoff_timestamp(snapshot_date: date) -> int:
    cutoff = datetime.combine(snapshot_date, daytime(23, 59, 59), tzinfo=LOCAL_TZ)
    return int(cutoff.timestamp())


def read_tree(tree: str, destination: Path) -> None:
    archive_bytes = subprocess.run(
        ["git", "archive", "--format=tar", tree],
        cwd=ROOT,
        capture_output=True,
        check=True,
    ).stdout
    destination.mkdir(parents=True)
    with tarfile.open(fileobj=io.BytesIO(archive_bytes), mode="r:") as archive:
        root = destination.resolve()
        for member in archive.getmembers():
            if member.issym() or member.islnk():
                raise RuntimeError(f"Dataset tree contains an unsupported link: {member.name}")
            target = (root / member.name).resolve()
            if target != root and root not in target.parents:
                raise RuntimeError(f"Unsafe path in dataset tree: {member.name}")
        archive.extractall(destination)


def validate_tree(tree: str) -> tuple[dict[str, Any], str, bool]:
    from vietlott_collector.repository_data import validate_repository_data

    with tempfile.TemporaryDirectory(prefix="vietlott-snapshot-") as temporary:
        path = Path(temporary) / "datasets"
        read_tree(tree, path)
        report = validate_repository_data(path)
        manifest_path = path / "metadata" / "snapshot-manifest.json"
        metadata_regenerated = False
        metadata_errors = {
            "Missing metadata/quality-report.json",
            "Missing metadata/snapshot-manifest.json",
        }
        errors = set(report.get("errors", []))
        if errors and errors.issubset(metadata_errors):
            from vietlott_collector.quality import write_quality_metadata

            write_quality_metadata(path)
            report = validate_repository_data(path)
            metadata_regenerated = True

        if manifest_path.is_file():
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            report["manifest_bytes"] = sum(
                int(entry.get("bytes", 0)) for entry in manifest.get("files", {}).values()
            )
        else:
            report["manifest_bytes"] = 0
        normalized_tree = write_tree_from_directory(path) if metadata_regenerated else tree
        return report, normalized_tree, metadata_regenerated


def write_tree_from_directory(directory: Path) -> str:
    entries: list[str] = []
    for path in sorted(directory.iterdir(), key=lambda item: item.name):
        if path.is_symlink():
            raise RuntimeError(f"Dataset contains an unsupported link: {path}")
        if path.is_dir():
            mode = "040000"
            object_type = "tree"
            object_id = write_tree_from_directory(path)
        else:
            mode = "100644"
            object_type = "blob"
            object_id = git("hash-object", "-w", "--no-filters", str(path))
        entries.append(f"{mode} {object_type} {object_id}\t{path.name}\n")
    return git("mktree", input_text="".join(entries))


def build_plan(
    source_ref: str,
    start_date: date | None,
    end_date: date,
) -> list[Snapshot]:
    commits = source_dataset_commits(source_ref)
    start = start_date or datetime.fromtimestamp(commits[0].timestamp, LOCAL_TZ).date()
    if start > end_date:
        raise ValueError(f"Start date {start} is after end date {end_date}")

    timestamps = [commit.timestamp for commit in commits]
    validations: dict[str, tuple[dict[str, Any], str, bool]] = {}
    snapshots: list[Snapshot] = []
    previous_tree: str | None = None
    current_date = start
    while current_date <= end_date:
        index = bisect.bisect_right(timestamps, cutoff_timestamp(current_date)) - 1
        if index < 0:
            raise RuntimeError(f"No dataset snapshot exists by the cutoff for {current_date}")
        commit = commits[index]
        if commit.tree not in validations:
            validations[commit.tree] = validate_tree(commit.tree)
            report, _, _ = validations[commit.tree]
            print(
                f"Validated {current_date}: {report.get('valid')} "
                f"({report.get('draw_rows')} draws, {report.get('prize_rows')} prizes)",
                flush=True,
            )
        validation, normalized_tree, metadata_regenerated = validations[commit.tree]
        snapshots.append(
            Snapshot(
                snapshot_date=current_date,
                source_commit=commit.sha,
                source_timestamp=commit.timestamp,
                source_tree=commit.tree,
                tree=normalized_tree,
                unchanged_from_previous_day=normalized_tree == previous_tree,
                metadata_regenerated=metadata_regenerated,
                validation=validation,
            )
        )
        previous_tree = normalized_tree
        current_date += timedelta(days=1)
    return snapshots


def create_snapshot_commits(snapshots: list[Snapshot]) -> list[tuple[Snapshot, str]]:
    readme_blob = git("hash-object", "-w", "--stdin", input_text=DATA_README)
    commits: list[tuple[Snapshot, str]] = []
    parent: str | None = None
    for snapshot in snapshots:
        tree_input = (
            f"100644 blob {readme_blob}\tREADME.md\n"
            f"040000 tree {snapshot.tree}\tdatasets\n"
        )
        root_tree = git("mktree", input_text=tree_input)
        cutoff = datetime.combine(
            snapshot.snapshot_date,
            daytime(23, 59, 59),
            tzinfo=LOCAL_TZ,
        )
        commit_env = os.environ.copy()
        commit_env.update(
            {
                "GIT_AUTHOR_NAME": BOT_NAME,
                "GIT_AUTHOR_EMAIL": BOT_EMAIL,
                "GIT_AUTHOR_DATE": cutoff.isoformat(timespec="seconds"),
                "GIT_COMMITTER_NAME": BOT_NAME,
                "GIT_COMMITTER_EMAIL": BOT_EMAIL,
                "GIT_COMMITTER_DATE": cutoff.isoformat(timespec="seconds"),
            }
        )
        args = ["git", "-c", "commit.gpgsign=false", "commit-tree", root_tree]
        if parent:
            args.extend(["-p", parent])
        args.extend(
            [
                "-m",
                f"data: daily snapshot {snapshot.snapshot_date.isoformat()}",
                "-m",
                (
                    f"Source main commit: {snapshot.source_commit}\n"
                    f"Source dataset tree: {snapshot.source_tree}"
                ),
            ]
        )
        result = subprocess.run(args, cwd=ROOT, env=commit_env, text=True, capture_output=True)
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or result.stdout.strip())
        parent = result.stdout.strip()
        commits.append((snapshot, parent))
    return commits


def remote_refs(pattern: str) -> dict[str, str]:
    output = git("ls-remote", "origin", pattern)
    return {ref: sha for sha, ref in (line.split("\t", maxsplit=1) for line in output.splitlines())}


def publish_plan(snapshots: list[Snapshot], data_branch: str) -> None:
    invalid_dates = [
        snapshot.snapshot_date.isoformat()
        for snapshot in snapshots
        if not snapshot.validation.get("valid")
    ]
    if invalid_dates:
        raise RuntimeError("Refusing to publish invalid snapshots: " + ", ".join(invalid_dates))

    print(f"Preparing {len(snapshots)} validated daily snapshots for publication", flush=True)
    commits = create_snapshot_commits(snapshots)
    expected_branch = commits[-1][1]
    expected_tags = {
        f"data-{snapshot.snapshot_date.isoformat()}": commit
        for snapshot, commit in commits
    }

    remote_branch = remote_refs(f"refs/heads/{data_branch}").get(f"refs/heads/{data_branch}")
    if remote_branch and remote_branch != expected_branch:
        raise RuntimeError(
            f"Remote branch {data_branch} already exists at {remote_branch}, "
            f"expected {expected_branch}. Refusing to replace it."
        )

    remote_tags = remote_refs("refs/tags/data-*")
    for tag, expected in expected_tags.items():
        remote_sha = remote_tags.get(f"refs/tags/{tag}")
        if remote_sha and remote_sha != expected:
            raise RuntimeError(f"Remote tag {tag} points to {remote_sha}, expected {expected}")

    local_branch = git("show-ref", "--verify", f"refs/heads/{data_branch}", check=False)
    if local_branch:
        local_sha = git("rev-parse", f"refs/heads/{data_branch}")
        if local_sha != expected_branch:
            raise RuntimeError(f"Local branch {data_branch} already exists at {local_sha}")
    else:
        git("update-ref", f"refs/heads/{data_branch}", expected_branch)

    for tag, expected in expected_tags.items():
        existing = git("show-ref", "--verify", f"refs/tags/{tag}", check=False)
        if existing:
            local_sha = git("rev-parse", f"{tag}^{{commit}}")
            if local_sha != expected:
                raise RuntimeError(f"Local tag {tag} points to {local_sha}, expected {expected}")
        else:
            git("update-ref", f"refs/tags/{tag}", expected)

    if not remote_branch:
        git("push", "origin", f"refs/heads/{data_branch}:refs/heads/{data_branch}")

    missing_tags = [
        tag for tag in expected_tags if f"refs/tags/{tag}" not in remote_tags
    ]
    for offset in range(0, len(missing_tags), 25):
        batch = missing_tags[offset : offset + 25]
        refspecs = [f"refs/tags/{tag}:refs/tags/{tag}" for tag in batch]
        git("push", "origin", *refspecs)

    repository = parse_repository(git("remote", "get-url", "origin"))
    subprocess.run(["gh", "auth", "status"], cwd=ROOT, check=True)
    today = datetime.now(LOCAL_TZ).date().isoformat()
    for snapshot, commit in commits:
        tag = f"data-{snapshot.snapshot_date.isoformat()}"
        exists = subprocess.run(
            ["gh", "release", "view", tag, "--repo", repository],
            cwd=ROOT,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        if exists.returncode == 0:
            print(f"Release {tag} already exists, skipping", flush=True)
            continue
        cutoff = datetime.combine(
            snapshot.snapshot_date,
            daytime(23, 59, 59),
            tzinfo=LOCAL_TZ,
        )
        notes = (
            f"Full dataset snapshot as of {cutoff.isoformat(timespec='seconds')}.\n\n"
            f"This historical release was backfilled on {today}. Its release publication "
            "date is the actual publication date, not the snapshot date.\n\n"
            f"Source main commit: `{snapshot.source_commit}`\n"
            f"Snapshot commit: `{commit}`\n"
            f"Draw rows: {snapshot.validation.get('draw_rows', 0)}\n"
            f"Prize rows: {snapshot.validation.get('prize_rows', 0)}\n"
            f"Uncompressed data bytes: {snapshot.validation.get('manifest_bytes', 0)}\n"
            + (
                "Legacy quality metadata and the file manifest were regenerated from the "
                "unchanged draw and prize files during backfill.\n"
                if snapshot.metadata_regenerated
                else ""
            )
            + "\nVerify the files using `datasets/metadata/snapshot-manifest.json`."
        )
        subprocess.run(
            [
                "gh",
                "release",
                "create",
                tag,
                "--repo",
                repository,
                "--verify-tag",
                "--title",
                f"Vietlott dataset {snapshot.snapshot_date.isoformat()}",
                "--notes",
                notes,
            ],
            cwd=ROOT,
            check=True,
        )
        print(f"Published release {tag}", flush=True)
        time.sleep(0.25)


def parse_repository(remote: str) -> str:
    match = re.search(r"github\.com[:/]([^/]+/[^/.]+?)(?:\.git)?$", remote)
    if not match:
        raise RuntimeError(f"Cannot determine GitHub repository from origin URL: {remote}")
    return match.group(1)


def report_dict(source_ref: str, snapshots: list[Snapshot]) -> dict[str, Any]:
    invalid = [
        snapshot.snapshot_date.isoformat()
        for snapshot in snapshots
        if not snapshot.validation.get("valid")
    ]
    unique_trees = {snapshot.tree for snapshot in snapshots}
    return {
        "source_ref": source_ref,
        "source_ref_commit": git("rev-parse", source_ref),
        "timezone": "Asia/Ho_Chi_Minh",
        "snapshot_count": len(snapshots),
        "unique_dataset_trees": len(unique_trees),
        "invalid_dates": invalid,
        "date_range": {
            "first": snapshots[0].snapshot_date.isoformat(),
            "last": snapshots[-1].snapshot_date.isoformat(),
        },
        "snapshots": [
            {
                "date": snapshot.snapshot_date.isoformat(),
                "source_commit": snapshot.source_commit,
                "source_commit_at_utc": datetime.fromtimestamp(
                    snapshot.source_timestamp, UTC
                ).isoformat(),
                "source_timestamp": snapshot.source_timestamp,
                "dataset_tree": snapshot.tree,
                "source_dataset_tree": snapshot.source_tree,
                "unchanged_from_previous_day": snapshot.unchanged_from_previous_day,
                "metadata_regenerated": snapshot.metadata_regenerated,
                "valid": bool(snapshot.validation.get("valid")),
                "draw_rows": snapshot.validation.get("draw_rows"),
                "prize_rows": snapshot.validation.get("prize_rows"),
                "manifest_bytes": snapshot.validation.get("manifest_bytes"),
                "errors": snapshot.validation.get("errors", []),
            }
            for snapshot in snapshots
        ],
    }


def snapshots_from_report(report: dict[str, Any], source_ref: str) -> list[Snapshot]:
    if report.get("source_ref") != source_ref:
        raise RuntimeError("The plan report was created from a different source ref")
    if report.get("source_ref_commit") != git("rev-parse", source_ref):
        raise RuntimeError("The source ref changed after this plan report was created")
    snapshots: list[Snapshot] = []
    for item in report.get("snapshots", []):
        validation = {
            "valid": item.get("valid"),
            "draw_rows": item.get("draw_rows"),
            "prize_rows": item.get("prize_rows"),
            "manifest_bytes": item.get("manifest_bytes"),
            "errors": item.get("errors", []),
        }
        snapshots.append(
            Snapshot(
                snapshot_date=date.fromisoformat(item["date"]),
                source_commit=item["source_commit"],
                source_timestamp=int(item["source_timestamp"]),
                source_tree=item["source_dataset_tree"],
                tree=item["dataset_tree"],
                unchanged_from_previous_day=bool(item["unchanged_from_previous_day"]),
                metadata_regenerated=bool(item["metadata_regenerated"]),
                validation=validation,
            )
        )
    if not snapshots:
        raise RuntimeError("The plan report contains no snapshots")
    return snapshots


def write_report(report: dict[str, Any], destination: Path | None) -> None:
    rendered = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if destination is None:
        print(rendered)
        return
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(rendered, encoding="utf-8")
    print(f"Wrote report to {destination}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Reconstruct and optionally publish daily data-only snapshots from Git history."
    )
    parser.add_argument("--source-ref", default="origin/main")
    parser.add_argument("--start-date", type=parse_date)
    parser.add_argument("--end-date", type=parse_date, default=latest_complete_local_date())
    parser.add_argument("--data-branch", default="datasets")
    parser.add_argument("--report", type=Path)
    parser.add_argument(
        "--plan-file",
        type=Path,
        help="Reuse a completed validation report instead of validating every day again.",
    )
    parser.add_argument(
        "--publish",
        action="store_true",
        help="Create the data-only branch, date tags, and GitHub Releases after validation.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.plan_file:
        report = json.loads(args.plan_file.read_text(encoding="utf-8"))
        snapshots = snapshots_from_report(report, args.source_ref)
    else:
        snapshots = build_plan(args.source_ref, args.start_date, args.end_date)
        report = report_dict(args.source_ref, snapshots)
    if args.report:
        write_report(report, args.report)
    elif not args.plan_file:
        write_report(report, None)
    invalid = report["invalid_dates"]
    if invalid:
        print("Historical snapshots failed validation: " + ", ".join(invalid), file=sys.stderr)
        return 1
    if args.publish:
        publish_plan(snapshots, args.data_branch)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
