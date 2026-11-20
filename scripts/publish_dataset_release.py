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
    output = run_git(
        repository,
        "ls-remote",
        "--tags",
        "origin",
        f"refs/tags/{tag}",
        f"refs/tags/{tag}^{{}}",
    )
    targets: dict[str, str] = {}
    for line in output.splitlines():
        parts = line.split("\t", maxsplit=1)
        if len(parts) == 2:
            target, reference = parts
            targets[reference] = target
    return targets.get(f"refs/tags/{tag}^{{}}", targets.get(f"refs/tags/{tag}"))


def _is_snapshot_tag(tag: str, base_tag: str) -> bool:
    if tag == base_tag:
        return True
    match = re.fullmatch(rf"{re.escape(base_tag)}-r(\d+)", tag)
    return match is not None and int(match.group(1)) >= 2


def _local_snapshot_tags(repository: Path, base_tag: str) -> dict[str, str]:
    output = run_git(repository, "tag", "--list", f"{base_tag}*")
    targets: dict[str, str] = {}
    for tag in output.splitlines():
        if not _is_snapshot_tag(tag, base_tag):
            continue
        target = run_git(
            repository,
            "rev-parse",
            "--verify",
            f"refs/tags/{tag}^{{commit}}",
            check=False,
        )
        if target:
            targets[tag] = target
    return targets


def _remote_snapshot_tags(repository: Path, base_tag: str) -> dict[str, str]:
    output = run_git(
        repository,
        "ls-remote",
        "--tags",
        "origin",
        f"refs/tags/{base_tag}*",
    )
    targets: dict[str, str] = {}
    for line in output.splitlines():
        target, reference = line.split("\t", maxsplit=1)
        reference = reference.removeprefix("refs/tags/")
        peeled = reference.endswith("^{}")
        tag = reference.removesuffix("^{}") if peeled else reference
        if not _is_snapshot_tag(tag, base_tag):
            continue
        if peeled or tag not in targets:
            targets[tag] = target
    return targets


def select_release_tag(repository: Path, day: date, head: str) -> str:
    base_tag = f"data-{day.isoformat()}"
    local_tags = _local_snapshot_tags(repository, base_tag)
    remote_tags = _remote_snapshot_tags(repository, base_tag)

    revision = 1
    while True:
        tag = base_tag if revision == 1 else f"{base_tag}-r{revision}"
        local_target = local_tags.get(tag)
        remote_target = remote_tags.get(tag)
        if local_target is None and remote_target is None:
            return tag
        if (
            local_target in {None, head}
            and remote_target in {None, head}
            and head in {local_target, remote_target}
        ):
            return tag
        revision += 1


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
        details = "\n".join(str(error) for error in report.get("errors", []))
        message = "Dataset validation failed."
        if details:
            message = f"{message}\n{details}"
        raise RuntimeError(message)

    base_tag = f"data-{day.isoformat()}"
    tag_match = TAG_PATTERN.fullmatch(base_tag)
    if not tag_match or tag_match.group(1) != day.isoformat():
        raise RuntimeError(f"Release tag {base_tag} is invalid.")
    head = run_git(repository, "rev-parse", "HEAD")
    tag = select_release_tag(repository, day, head)
    existing_remote = remote_tag(repository, tag)
    local_tag = run_git(
        repository,
        "rev-parse",
        "--verify",
        f"refs/tags/{tag}^{{commit}}",
        check=False,
    )
    if existing_remote and existing_remote != head:
        raise RuntimeError(f"Tag {tag} changed while selecting a release tag.")
    if local_tag and local_tag != head:
        raise RuntimeError(f"Local tag {tag} changed while selecting a release tag.")
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
    revision_match = re.fullmatch(r"data-\d{4}-\d{2}-\d{2}-r(\d+)", tag)
    revision = int(revision_match.group(1)) if revision_match else 1
    title = f"Vietlott dataset {day.isoformat()}"
    if revision > 1:
        title += f" (revision {revision})"
    notes = (
        "This full dataset snapshot was created at "
        f"{snapshot_cutoff.isoformat(timespec='seconds')}.\n\n"
        f"The snapshot commit is `{head}`.\n"
        f"The collector source commit is `{source_commit}`.\n"
        "The snapshot contains "
        f"{report.get('draw_rows', 0)} draw rows and "
        f"{report.get('prize_rows', 0)} prize rows.\n\n"
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
            title,
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
