"""Расчёт стоимости по почасовым ставкам с разбивкой день/ночь (как в Telegram-визитке)."""
from __future__ import annotations

import re
from typing import Any

DAY_START_MIN = 10 * 60
DAY_END_MIN = 22 * 60

NIGHT_HOUR_MULTIPLIER = 1.15
MIN_HOURS_DAY = 6
MIN_HOURS_WITH_NIGHT = 8


def parse_shift_interval(text: str) -> tuple[int, int] | None:
    t = (text or "").strip().replace("–", "-").replace("—", "-")
    m = re.search(r"(\d{1,2}):(\d{2})\s*-\s*(\d{1,2}):(\d{2})", t)
    if not m:
        return None
    h1, mi1, h2, mi2 = int(m.group(1)), int(m.group(2)), int(m.group(3)), int(m.group(4))
    if not (0 <= h1 <= 23 and 0 <= h2 <= 23 and 0 <= mi1 <= 59 and 0 <= mi2 <= 59):
        return None
    start = h1 * 60 + mi1
    end = h2 * 60 + mi2
    if start == end:
        return None
    return start, end


def _is_day_minute(m: int) -> bool:
    x = m % (24 * 60)
    return DAY_START_MIN <= x < DAY_END_MIN


def split_day_night_hours(start_min: int, end_min: int) -> tuple[float, float]:
    if end_min > start_min:
        duration_min = end_min - start_min
    else:
        duration_min = (24 * 60 - start_min) + end_min

    day_minutes = 0
    night_minutes = 0
    for d in range(duration_min):
        cm = (start_min + d) % (24 * 60)
        if _is_day_minute(cm):
            day_minutes += 1
        else:
            night_minutes += 1
    return day_minutes / 60.0, night_minutes / 60.0


def billable_hours(day_h: float, night_h: float) -> tuple[float, float, float]:
    total_actual = day_h + night_h
    if total_actual <= 0:
        return 0.0, 0.0, 0.0
    min_h = MIN_HOURS_WITH_NIGHT if night_h > 1e-9 else MIN_HOURS_DAY
    total_bill = max(total_actual, min_h)
    scale = total_bill / total_actual
    return day_h * scale, night_h * scale, total_bill


def cost_for_position(hourly_rate: int, day_h: float, night_h: float) -> float:
    d_b, n_b, _ = billable_hours(day_h, night_h)
    return d_b * hourly_rate + n_b * hourly_rate * NIGHT_HOUR_MULTIPLIER


def describe_shift_for_admin(start_min: int, end_min: int) -> str:
    day_h, night_h = split_day_night_hours(start_min, end_min)
    _, _, bill = billable_hours(day_h, night_h)
    has_night = night_h > 1e-9
    return (
        f"интервал {start_min // 60:02d}:{start_min % 60:02d}–{end_min // 60:02d}:{end_min % 60:02d}, "
        f"факт {day_h + night_h:.2f} ч (день {day_h:.2f} / ночь {night_h:.2f}), "
        f"к оплате {bill:.2f} ч/чел. ({'ночной минимум 8 ч' if has_night else 'дневной минимум 6 ч'})"
    )


def calculate_order_cost(
    staff_counts: dict[str, int],
    hourly_rates: dict[str, int],
    shift_parsed: tuple[int, int] | None,
) -> tuple[str, int, dict[str, Any]]:
    if not shift_parsed:
        return "—", 0, {"ok": False, "error": "bad_shift"}

    sm, em = shift_parsed
    day_h, night_h = split_day_night_hours(sm, em)
    meta = {
        "ok": True,
        "day_h": day_h,
        "night_h": night_h,
        "has_night": night_h > 1e-9,
        "shift_desc": describe_shift_for_admin(sm, em),
    }

    lines: list[str] = []
    total = 0
    for position, count in staff_counts.items():
        if count <= 0 or position not in hourly_rates:
            continue
        rate = hourly_rates[position]
        per = cost_for_position(rate, day_h, night_h)
        sub = int(round(per * count))
        nb = int((NIGHT_HOUR_MULTIPLIER - 1) * 100)
        line = (
            f"├─ {position}: {count} чел. "
            f"({rate} ₽/ч дн., +{nb}% ночь) = {sub:,} ₽"
        )
        lines.append(line.replace(",", " "))
        total += sub
    return "\n".join(lines) if lines else "—", total, meta
