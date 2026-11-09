"""Catch-up visit planning and the one-call ``check_card`` entry point."""

from __future__ import annotations

from datetime import date, timedelta

from . import rules
from .check import CardError, _DISCLAIMER, _parse_date, bucket, match_schedule, validate_card
from .schedules import load_schedule


def _earliest_day(slot: dict, age_days: int, last_age: dict[str, int],
                  planned: dict[str, int]) -> int:
    """First day offset (from today) this slot can be given."""
    gap = rules.CATCHUP_MIN_INTERVALS.get(slot["antigen"], rules.DEFAULT_CATCHUP_INTERVAL)
    earliest = 0
    min_months = slot.get("minimum_age_months")
    if min_months is not None:
        earliest = max(earliest, round(min_months * rules.DAYS_PER_MONTH) - age_days)
    for comp in slot["missing_components"]:
        if comp in planned:
            earliest = max(earliest, planned[comp] + gap)
        elif comp in last_age:
            earliest = max(earliest, last_age[comp] + rules.MIN_INTERVAL_DAYS - age_days)
    return max(earliest, 0)


def plan_catchup(needed: list[dict], age_days: int, valid: list[dict], today: date) -> list[dict]:
    last_age: dict[str, int] = {}
    for dose in valid:
        for comp in rules.components_for(dose["antigen"]):
            last_age[comp] = dose["age_days"]

    planned: dict[str, int] = {}
    visits: dict[int, list[dict]] = {}
    ordered = sorted(needed, key=lambda s: (s["antigen"] in rules.LIVE_VACCINES,
                                            s.get("recommended_age_months") or 0))
    for slot in ordered:
        day = _earliest_day(slot, age_days, last_age, planned)
        for existing in sorted(visits):
            clash = any(set(s["missing_components"]) & set(slot["missing_components"])
                        for s in visits[existing])
            if existing >= day and not clash:
                day = existing
                break
        visits.setdefault(day, []).append(slot)
        for comp in slot["missing_components"]:
            planned[comp] = day

    return [{
        "visit": n,
        "date": (today + timedelta(days=day)).isoformat(),
        "days_from_today": day,
        "give": [{"slot": f"{s['antigen']} dose {s['dose_number']}",
                  "for_components": s["missing_components"]} for s in visits[day]],
    } for n, day in enumerate(sorted(visits), start=1)]


def _flags(needed: list[dict], buckets: dict, age_days: int) -> list[str]:
    aged_out = buckets["aged_out"]
    flags = []
    antigens = {s["antigen"] for s in needed}
    if "Varicella" in antigens:
        flags.append("Varicella: ask about past chickenpox; if confirmed, the vaccine is not needed.")
    if aged_out:
        names = ", ".join(sorted({s["antigen"] for s in aged_out}))
        flags.append(f"Past the upper age limit, so not planned: {names}.")
    if buckets["missed_birth_dose"]:
        names = ", ".join(sorted({s["antigen"] for s in buckets["missed_birth_dose"]}))
        flags.append(f"Birth dose not recorded within 28 days: {names}. It is not given late; "
                     "the rest of the series still counts.")
    if age_days > 365:
        flags.append("Over 12 months: some catch-up rules differ from the infant series; confirm with a paediatrician.")
    return flags


def check_card(country: str, date_of_birth: str, doses: list[dict],
               today: str | None = None) -> dict:
    """Full check of one card against one country's schedule."""
    schedule = load_schedule(country)
    dob = _parse_date(date_of_birth, "date_of_birth")
    on = _parse_date(today, "today") if today else date.today()
    if on < dob:
        raise CardError("today is before date_of_birth")
    age_days = (on - dob).days

    valid, invalid = validate_card(dob, doses)
    buckets = bucket(match_schedule(schedule["doses"], valid), age_days)
    needed = buckets["overdue"] + buckets["due_now"] + [
        s for s in buckets["partial"]
        if (s["recommended_age_months"] or 0) <= age_days / rules.DAYS_PER_MONTH + rules.DUE_NOW_WINDOW_MONTHS
    ]
    return {
        "country": schedule["country"],
        "schedule_source": schedule["source"],
        "schedule_source_urls": schedule["source_urls"],
        "schedule_last_updated": schedule["last_updated"],
        "checked_on": on.isoformat(),
        "age_days": age_days,
        "summary": {k: len(v) for k, v in buckets.items()} | {"invalid_doses": len(invalid)},
        **buckets,
        "invalid_doses": invalid,
        "catch_up_visits": plan_catchup(needed, age_days, valid, on),
        "flags": _flags(needed, buckets, age_days),
        "rule_status": rules.RULE_STATUS,
        "disclaimer": _DISCLAIMER,
    }
