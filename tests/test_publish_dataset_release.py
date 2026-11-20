from __future__ import annotations

import subprocess
from datetime import date
from pathlib import Path

import vietlott_collector.repository_data as repository_data
from scripts import publish_dataset_release


def test_publish_release_creates_daily_tag_when_no_tag_exists(
    tmp_path: Path,
    monkeypatch,
) -> None:
    repository = tmp_path / "repository"
    origin = tmp_path / "origin.git"
    dataset = tmp_path / "datasets"
    dataset.mkdir()
    repository.mkdir()
    _run_git(tmp_path, "init", "--bare", str(origin))
    _run_git(repository, "init", "--initial-branch=main")
    _run_git(repository, "config", "user.name", "Snapshot Test")
    _run_git(repository, "config", "user.email", "snapshot@example.test")
    _run_git(repository, "config", "tag.gpgSign", "false")
    _run_git(repository, "config", "tag.forceSignAnnotated", "false")
    _write_commit(repository, "snapshot.txt", "valid", "initial snapshot")
    _run_git(repository, "remote", "add", "origin", str(origin))
    _run_git(repository, "push", "--set-upstream", "origin", "main")
    head = _run_git(repository, "rev-parse", "HEAD")

    monkeypatch.setattr(
        repository_data,
        "validate_repository_data",
        lambda _root: {"valid": True, "draw_rows": 1, "prize_rows": 1},
    )
    published_releases: set[str] = set()
    real_run = subprocess.run

    def fake_run(args, *positional, **options):
        if args[0] == "gh" and args[1:3] == ["release", "view"]:
            tag = args[3]
            return subprocess.CompletedProcess(args, int(tag not in published_releases), "", "")
        if args[0] == "gh" and args[1:3] == ["release", "create"]:
            published_releases.add(args[3])
            return subprocess.CompletedProcess(args, 0, "", "")
        return real_run(args, *positional, **options)

    monkeypatch.setattr(publish_dataset_release.subprocess, "run", fake_run)

    tag = "data-2026-11-19"
    result = publish_dataset_release.publish_release(
        repository,
        dataset,
        date(2026, 11, 19),
        source_commit="source-commit",
        github_repository="example/data",
    )

    assert result == f"Published {tag} at {head}"
    assert _run_git(repository, "rev-parse", f"refs/tags/{tag}^{{commit}}") == head
    assert _run_git(repository, "ls-remote", "origin", f"refs/tags/{tag}").split()[0] == head


def test_publish_release_uses_correction_tag_when_daily_tag_is_occupied(
    tmp_path: Path,
    monkeypatch,
) -> None:
    repository = tmp_path / "repository"
    origin = tmp_path / "origin.git"
    dataset = tmp_path / "datasets"
    dataset.mkdir()
    repository.mkdir()
    _run_git(tmp_path, "init", "--bare", str(origin))
    _run_git(repository, "init", "--initial-branch=main")
    _run_git(repository, "config", "user.name", "Snapshot Test")
    _run_git(repository, "config", "user.email", "snapshot@example.test")
    _run_git(repository, "config", "tag.gpgSign", "false")
    _run_git(repository, "config", "tag.forceSignAnnotated", "false")
    _write_commit(repository, "old.txt", "old", "initial snapshot")
    _run_git(repository, "remote", "add", "origin", str(origin))
    _run_git(repository, "push", "--set-upstream", "origin", "main")

    daily_tag = "data-2026-11-19"
    _run_git(repository, "tag", daily_tag)
    _run_git(repository, "push", "origin", f"refs/tags/{daily_tag}")
    _write_commit(repository, "new.txt", "new", "updated snapshot")
    _run_git(repository, "push", "origin", "main")
    head = _run_git(repository, "rev-parse", "HEAD")

    monkeypatch.setattr(
        repository_data,
        "validate_repository_data",
        lambda _root: {"valid": True, "draw_rows": 1, "prize_rows": 1},
    )
    published_releases: set[str] = set()
    real_run = subprocess.run

    def fake_run(args, *positional, **options):
        if args[0] == "gh" and args[1:3] == ["release", "view"]:
            tag = args[3]
            return subprocess.CompletedProcess(args, int(tag not in published_releases), "", "")
        if args[0] == "gh" and args[1:3] == ["release", "create"]:
            published_releases.add(args[3])
            return subprocess.CompletedProcess(args, 0, "", "")
        return real_run(args, *positional, **options)

    monkeypatch.setattr(publish_dataset_release.subprocess, "run", fake_run)

    result = publish_dataset_release.publish_release(
        repository,
        dataset,
        date(2026, 11, 19),
        source_commit="source-commit",
        github_repository="example/data",
    )

    correction_tag = f"{daily_tag}-r2"
    assert result == f"Published {correction_tag} at {head}"
    assert _run_git(repository, "rev-parse", f"refs/tags/{correction_tag}^{{commit}}") == head
    assert _run_git(repository, "ls-remote", "origin", f"refs/tags/{correction_tag}").split()[0] == head

    repeated_result = publish_dataset_release.publish_release(
        repository,
        dataset,
        date(2026, 11, 19),
        source_commit="source-commit",
        github_repository="example/data",
    )

    assert repeated_result == f"Release {correction_tag} already exists at {head}"

    _write_commit(repository, "later.txt", "later", "corrected snapshot")
    _run_git(repository, "push", "origin", "main")
    next_head = _run_git(repository, "rev-parse", "HEAD")
    next_result = publish_dataset_release.publish_release(
        repository,
        dataset,
        date(2026, 11, 19),
        source_commit="source-commit",
        github_repository="example/data",
    )

    next_correction_tag = f"{daily_tag}-r3"
    assert next_result == f"Published {next_correction_tag} at {next_head}"
    assert (
        _run_git(repository, "rev-parse", f"refs/tags/{next_correction_tag}^{{commit}}")
        == next_head
    )


def _write_commit(repository: Path, filename: str, content: str, message: str) -> None:
    (repository / filename).write_text(content, encoding="utf-8")
    _run_git(repository, "add", filename)
    _run_git(repository, "commit", "-m", message)


def _run_git(repository: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=repository,
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise AssertionError(f"git {' '.join(args)} failed: {result.stderr.strip()}")
    return result.stdout.strip()
