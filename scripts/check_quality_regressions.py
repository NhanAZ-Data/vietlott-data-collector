from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

ACTIVE_STALE_DAYS = {
    "keno": 2,
    "bingo18": 2,
    "lotto535": 10,
    "mega645": 10,
    "power655": 10,
    "max3d": 10,
    "max3dpro": 10,
}
SOURCE_RATE_TOLERANCE = 0.005


@dataclass(frozen=True, slots=True)
class Alert:
    product: str
    code: str
    message: str
    before: float | int | str | None = None
    after: float | int | str | None = None


def compare_quality_reports(
    before: dict[str, Any] | None,
    after: dict[str, Any],
    *,
    reference_date: date | None = None,
) -> list[Alert]:
    alerts: list[Alert] = []
    reference = reference_date or datetime.now(UTC).date()
    before_products = before.get("products", {}) if before else {}
    after_products = after.get("products", {})

    for product, profile in sorted(after_products.items()):
        stale_limit = ACTIVE_STALE_DAYS.get(product)
        last_date = _date(profile.get("last_date"))
        if stale_limit is not None and last_date is not None:
            age = (reference - last_date).days
            if age > stale_limit:
                alerts.append(
                    Alert(
                        product=product,
                        code="source_stale",
                        message=(
                            f"The latest data is {age} days old, exceeding the "
                            f"{stale_limit}-day monitoring threshold. This is a "
                            "source freshness warning and does not mean a draw is missing."
                        ),
                        after=profile.get("last_date"),
                    )
                )

        old = before_products.get(product)
        if not isinstance(old, dict):
            continue
        old_rows = max(int(old.get("rows", 0)), 1)
        new_rows = max(int(profile.get("rows", 0)), 1)
        old_unknown = _count(old, "source_origin", "unknown")
        new_unknown = _count(profile, "source_origin", "unknown")
        if new_unknown > old_unknown:
            alerts.append(
                Alert(
                    product=product,
                    code="unknown_source_increased",
                    message="The number of records with unknown sources increased.",
                    before=old_unknown,
                    after=new_unknown,
                )
            )

        old_secondary = _secondary_count(old)
        new_secondary = _secondary_count(profile)
        old_rate = old_secondary / old_rows
        new_rate = new_secondary / new_rows
        if new_rate - old_rate > SOURCE_RATE_TOLERANCE:
            alerts.append(
                Alert(
                    product=product,
                    code="secondary_source_rate_increased",
                    message=(
                        "The share of records with only secondary sources or pending "
                        "official verification increased by more than "
                        f"{SOURCE_RATE_TOLERANCE:.1%}."
                    ),
                    before=round(old_rate, 8),
                    after=round(new_rate, 8),
                )
            )

        old_pending = _count(old, "draw_confirmation", "not_confirmed")
        new_pending = _count(profile, "draw_confirmation", "not_confirmed")
        if new_pending > old_pending:
            alerts.append(
                Alert(
                    product=product,
                    code="not_confirmed_increased",
                    message="The number of unconfirmed draws increased.",
                    before=old_pending,
                    after=new_pending,
                )
            )
    return alerts


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Check dataset quality regressions")
    parser.add_argument("--before", type=Path)
    parser.add_argument("--after", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    before = _read_optional_json(args.before)
    after = json.loads(args.after.read_text(encoding="utf-8"))
    reference = _date(after.get("generated_from_dataset_at"))
    alerts = compare_quality_reports(before, after, reference_date=reference)
    payload = {
        "schema_version": 1,
        "reference_date": reference.isoformat() if reference else None,
        "alert_count": len(alerts),
        "alerts": [
            {
                "product": alert.product,
                "code": alert.code,
                "message": alert.message,
                "before": alert.before,
                "after": alert.after,
            }
            for alert in alerts
        ],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(_markdown_summary(alerts))
    return 0


def _read_optional_json(path: Path | None) -> dict[str, Any] | None:
    if path is None or not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _count(profile: dict[str, Any], group: str, key: str) -> int:
    values = profile.get(group, {})
    return int(values.get(key, 0)) if isinstance(values, dict) else 0


def _secondary_count(profile: dict[str, Any]) -> int:
    return (
        _count(profile, "source_verification", "single_secondary_source")
        + _count(profile, "source_verification", "pending_official")
        + _count(profile, "source_verification", "unknown")
    )


def _date(value: object) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _markdown_summary(alerts: list[Alert]) -> str:
    lines = ["## Dataset quality monitoring", ""]
    if not alerts:
        lines.append("No regressions found under the current warning thresholds.")
        return "\n".join(lines)
    lines.append(
        f"Found {len(alerts)} warning(s) that need review. "
        "Warnings do not confirm that a draw is missing."
    )
    lines.append("")
    for alert in alerts:
        change = ""
        if alert.before is not None:
            change = f" (before `{alert.before}`, after `{alert.after}`)."
        lines.append(f"- `{alert.product}` `{alert.code}` {alert.message}{change}")
    return "\n".join(lines)


if __name__ == "__main__":
    raise SystemExit(main())
