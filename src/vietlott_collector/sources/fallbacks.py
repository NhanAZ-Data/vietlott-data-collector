from __future__ import annotations

import json
import re
from datetime import date, datetime
from typing import Any

from bs4 import BeautifulSoup

from ..config import ProductSpec
from ..http import HttpClient
from ..models import DrawRecord
from ..validation import validate_draw
from .secondary import SecondaryBatch

XOSOVNM_KENO_URL = "https://api.xosovnm.net/api/vietlott/keno?limit=1000"
XEMNHANH_BASE_URL = "https://xemnhanh.vn"
BINGO18_URL = f"{XEMNHANH_BASE_URL}/vietlott/bingo18"
BINGO18_DRAW_URL = f"{BINGO18_URL}/ky/{{draw_id}}"
MAX_BINGO18_DRAWS = 1_000


class XosoVnmKenoSource:
    """Read recent Keno results from the public Xổ Số VN JSON API."""

    def __init__(self, client: HttpClient) -> None:
        self.client = client

    def fetch(
        self,
        spec: ProductSpec,
        *,
        existing_ids: set[str] | None = None,
        incomplete_prize_ids: set[str] | None = None,
    ) -> SecondaryBatch:
        del incomplete_prize_ids
        if spec.slug != "keno":
            raise ValueError(f"Xổ Số VN fallback does not support {spec.slug}")

        payload = json.loads(self.client.get_text(XOSOVNM_KENO_URL))
        raw_draws = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(raw_draws, list) or not raw_draws:
            raise RuntimeError("Xổ Số VN API returned no Keno draws")

        draws = [
            _parse_xosovnm_keno_draw(raw, spec)
            for raw in raw_draws
            if not _is_xosovnm_daily_summary(raw)
        ]
        if not draws:
            raise RuntimeError("Xổ Số VN API returned no identifiable Keno draws")
        ids = [int(record.draw_id) for record in draws]
        if len(ids) != len(set(ids)):
            raise RuntimeError("Xổ Số VN API returned duplicate Keno draw IDs")

        if existing_ids:
            highest_existing = max(int(draw_id) for draw_id in existing_ids)
            oldest_returned = min(ids)
            if oldest_returned > highest_existing and len(raw_draws) >= 1_000:
                raise RuntimeError(
                    "Xổ Số VN API result limit does not reach the latest stored Keno draw"
                )

        return SecondaryBatch(draws=draws, prizes=[], source_url=XOSOVNM_KENO_URL)


class XemNhanhBingo18Source:
    """Read Bingo18 draws by following Xem Nhanh's linked draw history."""

    def __init__(self, client: HttpClient) -> None:
        self.client = client

    def fetch(
        self,
        spec: ProductSpec,
        *,
        existing_ids: set[str] | None = None,
        incomplete_prize_ids: set[str] | None = None,
    ) -> SecondaryBatch:
        del incomplete_prize_ids
        if spec.slug != "bingo18":
            raise ValueError(f"Xem Nhanh fallback does not support {spec.slug}")

        listing_html = self.client.get_text(BINGO18_URL)
        latest_id = _latest_bingo18_draw_id(listing_html)
        highest_existing = (
            max((int(draw_id) for draw_id in existing_ids), default=latest_id)
            if existing_ids
            else latest_id
        )
        if latest_id < highest_existing:
            raise RuntimeError(
                f"Xem Nhanh latest Bingo18 draw {latest_id:07d} is behind stored draw "
                f"{highest_existing:07d}"
            )

        draws: list[DrawRecord] = []
        current_id = latest_id
        for _ in range(MAX_BINGO18_DRAWS):
            detail_url = BINGO18_DRAW_URL.format(draw_id=f"{current_id:07d}")
            detail_html = self.client.get_text(detail_url)
            record = _parse_xemnhanh_bingo18_draw(
                detail_html,
                draw_id=f"{current_id:07d}",
                source_url=detail_url,
                spec=spec,
            )
            draws.append(record)
            if current_id <= highest_existing:
                break

            previous_id = _previous_bingo18_draw_id(detail_html)
            if previous_id is None or previous_id >= current_id:
                raise RuntimeError(
                    f"Xem Nhanh Bingo18 draw {current_id:07d} has no valid previous draw link"
                )
            current_id = previous_id
        else:
            raise RuntimeError(
                f"Xem Nhanh Bingo18 history did not reach stored draw "
                f"{highest_existing:07d} within {MAX_BINGO18_DRAWS} draws"
            )

        return SecondaryBatch(draws=draws, prizes=[], source_url=BINGO18_URL)


def _parse_xosovnm_keno_draw(raw: Any, spec: ProductSpec) -> DrawRecord:
    if not isinstance(raw, dict) or not isinstance(raw.get("data"), dict):
        raise RuntimeError("Xổ Số VN API returned a malformed Keno draw")
    title = str(raw.get("title", ""))
    id_match = re.search(r"#(\d+)", title)
    if id_match is None:
        raise RuntimeError(f"Xổ Số VN Keno draw has no draw ID: {title!r}")

    date_text = raw.get("date")
    try:
        draw_date = datetime.strptime(str(date_text), "%d/%m/%Y").date()
    except ValueError as exc:
        raise RuntimeError(
            f"Xổ Số VN Keno draw {id_match.group(1)} has an invalid date"
        ) from exc

    raw_numbers = raw["data"].get("numbers")
    if not isinstance(raw_numbers, list):
        raise RuntimeError(
            f"Xổ Số VN Keno draw {id_match.group(1)} has no number list"
        )
    numbers = [int(number) for number in raw_numbers]
    even = sum(number % 2 == 0 for number in numbers)
    small = sum(number <= 40 for number in numbers)
    draw_id = id_match.group(1).zfill(7)
    record = DrawRecord(
        product=spec.slug,
        draw_id=draw_id,
        draw_date=draw_date,
        result={"numbers": numbers},
        attributes={
            "data_source": "xosovnm_net_api",
            "official_verification_status": "pending",
            "secondary_source_url": XOSOVNM_KENO_URL,
            "upstream_claimed_source": "Vietlott",
            "odd_even": {"even": even, "odd": len(numbers) - even},
            "big_small": {"big": len(numbers) - small, "small": small},
        },
        source_url=XOSOVNM_KENO_URL,
        prize_status="rules_available",
    )
    warnings = validate_draw(record, spec)
    if warnings:
        raise RuntimeError(
            f"Xổ Số VN Keno draw {draw_id} failed validation: "
            + "; ".join(warnings)
        )
    return record


def _is_xosovnm_daily_summary(raw: Any) -> bool:
    if not isinstance(raw, dict):
        return False
    title = str(raw.get("title", ""))
    return re.fullmatch(
        r"Kết quả xổ số Keno ngày \d{2}/\d{2}/\d{4}",
        title,
        flags=re.IGNORECASE,
    ) is not None


def _latest_bingo18_draw_id(html: str) -> int:
    soup = BeautifulSoup(html, "html.parser")
    draw_ids = {
        int(match.group(1))
        for anchor in soup.select("a[href]")
        if (match := re.search(r"/vietlott/bingo18/ky/(\d{7})/?$", anchor["href"]))
    }
    if not draw_ids:
        raise RuntimeError("Xem Nhanh Bingo18 page contains no draw links")
    return max(draw_ids)


def _parse_xemnhanh_bingo18_draw(
    html: str,
    *,
    draw_id: str,
    source_url: str,
    spec: ProductSpec,
) -> DrawRecord:
    soup = BeautifulSoup(html, "html.parser")
    section = next(
        (
            candidate
            for candidate in soup.select("main section")
            if any(
                draw_id in heading.get_text(" ", strip=True)
                for heading in candidate.select("h2")
            )
        ),
        None,
    )
    if section is None:
        raise RuntimeError(f"Xem Nhanh page has no Bingo18 draw {draw_id}")

    date_tag = section.select_one("time[datetime]")
    if date_tag is None:
        raise RuntimeError(f"Xem Nhanh Bingo18 draw {draw_id} has no draw date")
    try:
        draw_date = date.fromisoformat(str(date_tag["datetime"]))
    except ValueError as exc:
        raise RuntimeError(f"Xem Nhanh Bingo18 draw {draw_id} has an invalid date") from exc

    number_container = section.select_one("div.d-flex.flex-wrap.gap-2")
    if number_container is None:
        raise RuntimeError(f"Xem Nhanh Bingo18 draw {draw_id} has no result numbers")
    digits = [
        int(value.get_text(strip=True))
        for value in number_container.find_all("strong", recursive=False)
    ]
    if len(digits) != 3:
        raise RuntimeError(
            f"Xem Nhanh Bingo18 draw {draw_id} has {len(digits)} result numbers"
        )

    total = sum(digits)
    reported_total = next(
        (
            value.find_next_sibling("dd").get_text(strip=True)
            for value in section.select("dt")
            if value.get_text(strip=True).casefold() == "tổng"
            and value.find_next_sibling("dd") is not None
        ),
        None,
    )
    if reported_total is not None and int(reported_total) != total:
        raise RuntimeError(
            f"Xem Nhanh Bingo18 draw {draw_id} total does not match its digits"
        )

    record = DrawRecord(
        product=spec.slug,
        draw_id=draw_id,
        draw_date=draw_date,
        result={"digits": digits},
        attributes={
            "data_source": "xemnhanh_vn",
            "official_verification_status": "pending",
            "secondary_source_url": source_url,
            "upstream_claimed_source": "Vietlott",
            "total": total,
            "has_duplicate": len(set(digits)) != len(digits),
        },
        source_url=source_url,
        prize_status="rules_available",
    )
    warnings = validate_draw(record, spec)
    if warnings:
        raise RuntimeError(
            f"Xem Nhanh Bingo18 draw {draw_id} failed validation: "
            + "; ".join(warnings)
        )
    return record


def _previous_bingo18_draw_id(html: str) -> int | None:
    soup = BeautifulSoup(html, "html.parser")
    for anchor in soup.select("main a[href]"):
        if "kỳ trước" not in anchor.get_text(" ", strip=True).casefold():
            continue
        match = re.search(r"/vietlott/bingo18/ky/(\d{7})/?$", anchor["href"])
        if match is not None:
            return int(match.group(1))
    return None
