from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_dataset_workflow_preserves_before_and_after_diagnostics() -> None:
    workflow = (
        ROOT / ".github" / "workflows" / "update-dataset.yml"
    ).read_text(encoding="utf-8")

    assert "vietlott-reports/before" in workflow
    assert 'after_dir="$report_dir/after"' in workflow
    assert "vietlott-repository-data audit" in workflow
    assert "check_quality_regressions.py" in workflow
    assert "quality-regressions.json" in workflow
    assert "actions/upload-artifact@v7" in workflow
    assert "vietlott-dataset-writer" in workflow
    assert "path: dataset-branch" in workflow
    assert "git -C dataset-branch push origin HEAD:datasets" in workflow
    assert "dataset-branch/datasets" in workflow
    assert "HEAD:main" not in workflow
    assert "site/" not in workflow
    assert "prediction" not in workflow.lower()


def test_collector_workflows_do_not_request_pages_permissions() -> None:
    workflows = [
        ROOT / ".github" / "workflows" / "ci.yml",
        ROOT / ".github" / "workflows" / "update-dataset.yml",
        ROOT / ".github" / "workflows" / "update-fast.yml",
        ROOT / ".github" / "workflows" / "update-scheduled.yml",
        ROOT / ".github" / "workflows" / "release-dataset.yml",
    ]

    for path in workflows:
        workflow = path.read_text(encoding="utf-8")
        assert "pages: write" not in workflow
        assert "id-token: write" not in workflow


def test_web_and_prediction_workflows_are_removed() -> None:
    workflow_dir = ROOT / ".github" / "workflows"
    names = {path.name for path in workflow_dir.glob("*.yml")}
    assert "build-pages.yml" not in names
    assert names == {
        "ci.yml",
        "release-dataset.yml",
        "update-dataset.yml",
        "update-fast.yml",
        "update-scheduled.yml",
    }


def test_nightly_release_uses_the_shared_dataset_writer() -> None:
    workflow = (ROOT / ".github" / "workflows" / "release-dataset.yml").read_text(
        encoding="utf-8"
    )

    assert 'cron: "30 17 * * *"' in workflow
    assert "uses: ./.github/workflows/update-dataset.yml" in workflow
    assert "publish_release: true" in workflow
