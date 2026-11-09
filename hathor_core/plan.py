"""Catch-up visit planning and the one-call ``check_card`` entry point."""

from __future__ import annotations

from datetime import date, timedelta

from . import rules
from .check import CardError, _DISCLAIMER, _parse_date, bucket, match_schedule, validate_card
from .schedules import load_schedule


def _is_live_parenteral(slot: dict) -> bool:
    names = {slot["antigen"], *slot["missing_components"]}
    return bool(names & rules.LIVE_PARENTERAL)


def _earliest_day(slot: dict, age_days: int, last_age: dict[str, int],
                  planned: dict[str, int], last_live_given: int | None) -> int:
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
    if last_live_given is not None and last_live_given != age_days and _is_live_parenteral(slot):
        earliest = max(earliest, last_live_given + rules.LIVE_SPACING_DAYS - age_days)
    return max(earliest, 0)


def _choose_day(slot: dict, earliest: int, visits: dict[int, list[dict]],
                live_days: set[int]) -> int:
    """Join a nearby visit when allowed; keep live vaccines same-day or 28 days apart."""
    live = _is_live_parenteral(slot)
    while True:
        day = earliest
        for existing in sorted(visits):
            clash = any(set(s["missing_components"]) & set(slot["missing_components"])
                        for s in visits[existing])
            if earliest <= existing <= earliest + rules.VISIT_JOIN_WINDOW_DAYS and not clash:
                day = existing
                break
        conflicts = [d for d in live_days if 0 < abs(d - day) < rules.LIVE_SPACING_DAYS] if live else []
        if not conflicts:
            return day
        earliest = max(conflicts) + rules.LIVE_SPACING_DAYS


def plan_catchup(needed: list[dict], age_days: int, valid: list[dict], today: date) -> list[dict]:
    last_age: dict[str, int] = {}
    last_live_given = None
    for dose in valid:
        for comp in dose["components"]:
            last_age[comp] = dose["age_days"]
        if {dose["antigen"], *dose["components"]} & rules.LIVE_PARENTERAL:
            last_live_given = dose["age_days"]

    planned: dict[str, int] = {}
    visits: dict[int, list[dict]] = {}
    live_days: set[int] = set()
    ordered = sorted(needed, key=lambda s: (s["antigen"] in rules.LIVE_VACCINES,
                                            s.get("recommended_age_months") or 0))
    for slot in ordered:
        earliest = _earliest_day(slot, age_days, last_age, planned, last_live_given)
        day = _choose_day(slot, earliest, visits, live_days)
        visits.setdefault(day, []).append(slot)
        if _is_live_parenteral(slot):
            live_days.add(day)
        for comp in slot["missing_components"]:
            planned[comp] = day

    return [{
        "visit": n,
        "date": (today + timedelta(days=day)).isoformat(),
        "days_from_today": day,
        "give": [{"slot": f"{s['antigen']} dose {s['dose_number']}",
                  "for_components": s["missing_components"]} for s in visits[day]],
    } for n, day in enumerate(sorted(visits), start=1)]


def _flags(needed: list[dict], buckets: dict, age_days: int,
           unrecognised: list[dict], not_in_schedule: list[dict]) -> list[str]:
    aged_out = buckets["aged_out"]
    flags = []
    if unrecognised:
        labels = ", ".join(sorted({d["antigen"] for d in unrecognised}))
        flags.append(f"Not recognised, so not counted: {labels}. Check these card labels.")
    if not_in_schedule:
        names = ", ".join(sorted({d["antigen"] for d in not_in_schedule}))
        flags.append(f"Given but not part of this schedule (kept on record, not needed here): {names}.")
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

    valid, invalid, unrecognised = validate_card(dob, doses, age_days)
    buckets = bucket(match_schedule(schedule["doses"], valid), age_days)
    in_schedule = {c for d in schedule["doses"] for c in rules.components_for(d["antigen"])}
    not_in_schedule = [d for d in valid if not set(d["components"]) & in_schedule]
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
        "summary": {k: len(v) for k, v in buckets.items()} | {
            "invalid_doses": len(invalid), "unrecognised_doses": len(unrecognised),
            "not_in_this_schedule": len(not_in_schedule)},
        **buckets,
        "invalid_doses": invalid,
        "unrecognised_doses": unrecognised,
        "not_in_this_schedule": not_in_schedule,
        "catch_up_visits": plan_catchup(needed, age_days, valid, on),
        "flags": _flags(needed, buckets, age_days, unrecognised, not_in_schedule),
        "rule_status": rules.RULE_STATUS,
        "disclaimer": _DISCLAIMER,
    }
