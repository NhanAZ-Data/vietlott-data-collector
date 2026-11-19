from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

LOCAL_TZ = ZoneInfo("Asia/Ho_Chi_Minh")
TAG_PATTERN = re.compile(r"data-(\d{4}-\d{2}-\d{2})\Z")


def run_git(repository: Path, *args: str, check: bool = True) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=repository,
        text=True,
        capture_output=True,
        check=False,
    )
    if check and result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip())
    return result.stdout.strip()


def snapshot_date(value: str | None, now: datetime | None = None) -> date:
    if value:
        try:
            parsed = date.fromisoformat(value)
        except ValueError as exc:
            raise ValueError("Snapshot date must use YYYY-MM-DD") from exc
        if parsed.isoformat() != value:
            raise ValueError("Snapshot date must use YYYY-MM-DD")
        return parsed
    current = (now or datetime.now(LOCAL_TZ)).astimezone(LOCAL_TZ).date()
    return current - timedelta(days=1)


def remote_tag(repository: Path, tag: str) -> str | None:
    output = run_git(repository, "ls-remote", "origin", f"refs/tags/{tag}")
    if not output:
        return None
    return output.split("\t", maxsplit=1)[0]


def publish_release(
    repository: Path,
    data_dir: Path,
    day: date,
    source_commit: str,
    github_repository: str,
) -> str:
    from vietlott_collector.repository_data import validate_repository_data

    report = validate_repository_data(data_dir)
    if not report.get("valid"):
        details = "; ".join(str(error) for error in report.get("errors", []))
        raise RuntimeError(f"Dataset failed validation: {details}")

    tag = f"data-{day.isoformat()}"
    tag_match = TAG_PATTERN.fullmatch(tag)
    if not tag_match or tag_match.group(1) != day.isoformat():
        raise RuntimeError(f"Invalid release tag: {tag}")

    head = run_git(repository, "rev-parse", "HEAD")
    existing_remote = remote_tag(repository, tag)
    if existing_remote and existing_remote != head:
        raise RuntimeError(
            f"Tag {tag} already points to {existing_remote}, current dataset commit is {head}. "
            "Use a correction tag such as data-YYYY-MM-DD-r2 instead of replacing it."
        )

    local_tag = run_git(repository, "rev-parse", f"refs/tags/{tag}^{{commit}}", check=False)
    if local_tag and local_tag != head:
        raise RuntimeError(f"Local tag {tag} points to {local_tag}, current dataset commit is {head}")
    if not existing_remote:
        if local_tag:
            run_git(repository, "push", "origin", f"refs/tags/{tag}:refs/tags/{tag}")
        else:
            run_git(repository, "tag", tag, head)
            run_git(repository, "push", "origin", f"refs/tags/{tag}:refs/tags/{tag}")

    exists = subprocess.run(
        ["gh", "release", "view", tag, "--repo", github_repository],
        cwd=ROOT,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    if exists.returncode == 0:
        return f"Release {tag} already exists at {head}"

    snapshot_cutoff = datetime.combine(day, datetime.min.time(), tzinfo=LOCAL_TZ) + timedelta(
        days=1, seconds=-1
    )
    notes = (
        f"Full dataset snapshot as of {snapshot_cutoff.isoformat(timespec='seconds')}.\n\n"
        f"Snapshot commit: `{head}`\n"
        f"Collector source commit: `{source_commit}`\n"
        f"Draw rows: {report.get('draw_rows', 0)}\n"
        f"Prize rows: {report.get('prize_rows', 0)}\n\n"
        "Verify individual files with `datasets/metadata/snapshot-manifest.json`."
    )
    subprocess.run(
        [
            "gh",
            "release",
            "create",
            tag,
            "--repo",
            github_repository,
            "--verify-tag",
            "--title",
            f"Vietlott dataset {day.isoformat()}",
            "--notes",
            notes,
        ],
        cwd=ROOT,
        check=True,
    )
    return f"Published {tag} at {head}"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Publish a validated daily Vietlott dataset snapshot.")
    parser.add_argument("--repository-dir", type=Path, default=ROOT)
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--snapshot-date")
    parser.add_argument("--source-commit", default=os.environ.get("GITHUB_SHA", "unknown"))
    parser.add_argument("--github-repository", default=os.environ.get("GITHUB_REPOSITORY", ""))
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    day = snapshot_date(args.snapshot_date)
    repository = args.repository_dir.resolve()
    data_dir = args.data_dir.resolve()
    github_repository = args.github_repository
    if not github_repository:
        raise SystemExit("GITHUB_REPOSITORY or --github-repository is required")
    message = publish_release(
        repository,
        data_dir,
        day,
        args.source_commit,
        github_repository,
    )
    print(message)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
