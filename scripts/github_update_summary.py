from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def render_summary(
    update_report: dict[str, Any] | None,
    validation_report: dict[str, Any] | None,
) -> str:
    lines = ["## Vietlott update results", ""]
    if update_report is None:
        lines.extend(
            [
                "No update report found. Check the collection step logs.",
                "",
            ]
        )
    else:
        products = ", ".join(update_report.get("products", [])) or "unknown"
        fallbacks = sorted(update_report.get("secondary_fallback", {}))
        lines.extend(
            [
                "| Metric | Value |",
                "| --- | ---: |",
                f"| Products | {products} |",
                f"| New draws | {int(update_report.get('new_draw_rows', 0)):,} |",
                f"| New prize rows | {int(update_report.get('new_prize_rows', 0)):,} |",
                f"| Total draws after update | {int(update_report.get('draw_rows_after', 0)):,} |",
                f"| Unresolved source errors | {int(update_report.get('source_errors', 0)):,} |",
                (
                    "| Official-source access errors | "
                    f"{int(update_report.get('official_source_errors', 0)):,} |"
                ),
                "",
                (
                    "The collector used a secondary fallback for "
                    + ", ".join(fallbacks)
                    + "."
                    if fallbacks
                    else "The collector did not use a secondary fallback."
                ),
                "",
            ]
        )

    if validation_report is None:
        lines.extend(
            [
                "No dataset validation report found.",
                "",
            ]
        )
    else:
        valid = bool(validation_report.get("valid"))
        errors = validation_report.get("errors", [])
        error_count = len(errors)
        error_label = "error" if error_count == 1 else "errors"
        lines.extend(
            [
                f"The dataset {'passed' if valid else 'failed'} validation.",
                "",
                (
                    "The snapshot contains "
                    f"{int(validation_report.get('draw_rows', 0)):,} draw rows and "
                    f"{int(validation_report.get('prize_rows', 0)):,} prize rows."
                ),
                f"Validation reported {error_count} {error_label}.",
                "",
            ]
        )
        if errors:
            lines.extend(f"- {error}" for error in errors[:20])
            lines.append("")
    return "\n".join(lines)


def _read_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} does not contain a JSON object")
    return value


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build an English GitHub Actions update summary"
    )
    parser.add_argument("--update-report", type=Path, required=True)
    parser.add_argument("--validation-report", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    summary = render_summary(
        _read_json(args.update_report),
        _read_json(args.validation_report),
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(summary)
        handle.write("\n")


if __name__ == "__main__":
    main()
