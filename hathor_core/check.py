"""Check a child's vaccine card against a sourced schedule.

Pipeline (all deterministic, no model calls):
1. ``validate_card``: age at each dose, then minimum age, maximum age and
   minimum interval per component. Invalid doses are kept with reasons.
2. ``match_schedule``: credit valid doses to schedule slots in age order,
   component by component, so a Pentavalent dose credits the DTP, HepB and
   Hib parts of the next open slots and leaves IPV open.
3. ``bucket``: completed / partial / overdue / due now / upcoming / aged out.
4. ``plan_catchup``: group what is needed now into visits that respect
   minimum intervals, minimum ages and the last dose already given.
"""

from __future__ import annotations

from datetime import date, datetime

from . import rules

_DISCLAIMER = (
    "Decision support, not a prescription. A licensed paediatrician or the "
    "local vaccination service must confirm the plan."
)


class CardError(ValueError):
    """Raised when the card input cannot be read."""


def _parse_date(value: object, field: str) -> date:
    if isinstance(value, date):
        return value
    try:
        return datetime.strptime(str(value).strip(), "%Y-%m-%d").date()
    except ValueError as exc:
        raise CardError(f"{field} must be YYYY-MM-DD, got {value!r}") from exc


def _dose_reasons(antigen: str, age: int, last_age: dict[str, int]) -> list[str]:
    reasons = []
    if age < 0:
        reasons.append(f"Given {-age} days before the date of birth: re-check the year on the card.")
        return reasons
    min_age = rules.MIN_AGE_DAYS.get(antigen, rules.DEFAULT_MIN_AGE_DAYS)
    if age < min_age:
        reasons.append(f"Given at {age} days; minimum age for {antigen} is {min_age} days.")
    max_age = rules.MAX_AGE_DAYS.get(antigen)
    if max_age is not None and age > max_age:
        reasons.append(f"Given at {age} days; {antigen} is not given after {max_age} days.")
    for comp in rules.components_for(antigen):
        prior = last_age.get(comp)
        if prior is not None and age - prior < rules.MIN_INTERVAL_DAYS:
            reasons.append(
                f"{comp}: only {age - prior} days after the previous dose "
                f"(minimum {rules.MIN_INTERVAL_DAYS})."
            )
    return reasons


def validate_card(dob: date, doses: list[dict]) -> tuple[list[dict], list[dict]]:
    """Return (valid, invalid) doses, each with ``age_days``, sorted by age."""
    if not isinstance(doses, list):
        raise CardError("doses must be a list")
    parsed = []
    for i, dose in enumerate(doses):
        if not isinstance(dose, dict) or not str(dose.get("antigen", "")).strip():
            raise CardError(f"dose {i + 1} needs an antigen")
        given = _parse_date(dose.get("date_given"), f"dose {i + 1} date_given")
        parsed.append({"antigen": str(dose["antigen"]).strip(),
                       "date_given": given.isoformat(), "age_days": (given - dob).days})
    parsed.sort(key=lambda d: d["age_days"])

    valid, invalid, last_age = [], [], {}
    for dose in parsed:
        reasons = _dose_reasons(dose["antigen"], dose["age_days"], last_age)
        if reasons:
            invalid.append({**dose, "reasons": reasons})
            continue
        valid.append(dose)
        for comp in rules.components_for(dose["antigen"]):
            last_age[comp] = dose["age_days"]
    return valid, invalid


def _slot_order(slot: dict) -> tuple:
    rec = slot.get("recommended_age_months")
    return (rec if rec is not None else 10_000, slot.get("dose_number") or 0)


def _is_birth_slot(slot: dict) -> bool:
    if slot.get("birth_dose"):
        return True
    return (slot.get("recommended_age_months") == 0
            and slot["antigen"] in rules.BIRTH_DOSE_ANTIGENS)


def match_schedule(schedule: list[dict], valid: list[dict]) -> list[dict]:
    """Credit valid doses to slots in age order, per component."""
    pools: dict[str, list[dict]] = {}
    for dose in valid:
        for comp in rules.components_for(dose["antigen"]):
            pools.setdefault(comp, []).append(dose)
    cursor = {comp: 0 for comp in pools}

    matched = []
    for slot in sorted(schedule, key=_slot_order):
        required = rules.components_for(slot["antigen"])
        birth = _is_birth_slot(slot)
        covered, via = [], set()
        for comp in required:
            pool = pools.get(comp, [])
            if cursor.get(comp, 0) < len(pool):
                credited = pool[cursor[comp]]
                if birth and credited["age_days"] > rules.BIRTH_DOSE_WINDOW_DAYS:
                    continue
                cursor[comp] = cursor.get(comp, 0) + 1
                covered.append(comp)
                if credited["antigen"] != slot["antigen"]:
                    via.add(credited["antigen"])
        matched.append({
            "antigen": slot["antigen"],
            "dose_number": slot.get("dose_number"),
            "category": slot.get("category", "compulsory"),
            "recommended_age_months": slot.get("recommended_age_months"),
            "minimum_age_months": slot.get("minimum_age_months"),
            "required_components": list(required),
            "missing_components": [c for c in required if c not in covered],
            "credited_from": sorted(via),
            "birth_slot": birth,
            "source_note": slot.get("verification_source"),
        })
    return matched


def _aged_out(slot: dict, age_days: int) -> bool:
    for name in (slot["antigen"], *slot["missing_components"]):
        limit = rules.MAX_AGE_DAYS.get(name)
        if limit is not None and age_days > limit:
            return True
    return False


def bucket(matched: list[dict], age_days: int) -> dict[str, list[dict]]:
    age_months = age_days / rules.DAYS_PER_MONTH
    out = {k: [] for k in ("completed", "partial", "overdue", "due_now", "upcoming",
                           "aged_out", "missed_birth_dose")}
    for slot in matched:
        rec = slot["recommended_age_months"]
        if not slot["missing_components"]:
            out["completed"].append(slot)
        elif slot["birth_slot"]:
            out["missed_birth_dose"].append(slot)
        elif _aged_out(slot, age_days):
            out["aged_out"].append(slot)
        elif len(slot["missing_components"]) < len(slot["required_components"]):
            out["partial"].append(slot)
        elif rec is not None and rec < age_months - rules.DUE_NOW_WINDOW_MONTHS:
            out["overdue"].append({**slot, "months_overdue": round(age_months - rec, 1)})
        elif rec is None or rec <= age_months + rules.DUE_NOW_WINDOW_MONTHS:
            out["due_now"].append(slot)
        else:
            out["upcoming"].append(slot)
    return out
