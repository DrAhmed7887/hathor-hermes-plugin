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
from .schedules import all_schedule_antigens

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


def canonical_antigen(raw: str) -> str | None:
    """Map a card label to the engine's antigen name, or None if unknown."""
    key = " ".join(str(raw).replace("-", " ").replace("_", " ").lower().split())
    if key in rules.ANTIGEN_ALIASES:
        return rules.ANTIGEN_ALIASES[key]
    for name in _known_antigens():
        if name.lower() == key or name.lower().replace("-", " ") == key:
            return name
    return None


def _known_antigens() -> set[str]:
    return set(rules.COMPONENTS) | set(rules.MIN_AGE_DAYS) | all_schedule_antigens()


def _whole_dose_reasons(antigen: str, age: int, age_today: int) -> list[str]:
    if age < 0:
        return [f"Given {-age} days before the date of birth: re-check the year on the card."]
    if age > age_today:
        return ["Dated after today: re-check the date on the card."]
    reasons = []
    min_age = rules.MIN_AGE_DAYS.get(antigen, rules.DEFAULT_MIN_AGE_DAYS)
    if age < min_age:
        reasons.append(f"Given at {age} days; minimum age for {antigen} is {min_age} days.")
    max_age = rules.MAX_AGE_DAYS.get(antigen)
    if max_age is not None and age > max_age:
        reasons.append(f"Given at {age} days; {antigen} is not given after {max_age} days.")
    return reasons


def _component_check(antigen: str, age: int, last_age: dict[str, int]) -> tuple[list[str], list[str]]:
    """Split a dose's components into (counted, reasons for the ones dropped)."""
    counted, dropped = [], []
    for comp in rules.components_for(antigen):
        prior = last_age.get(comp)
        if prior is None or age - prior >= rules.MIN_INTERVAL_DAYS:
            counted.append(comp)
        elif age == prior:
            dropped.append(f"{comp}: already given the same day, not counted twice.")
        else:
            dropped.append(f"{comp}: only {age - prior} days after the previous dose "
                           f"(minimum {rules.MIN_INTERVAL_DAYS}), so not counted.")
    return counted, dropped


def _parse_doses(dob: date, doses: list) -> tuple[list[dict], list[dict]]:
    if not isinstance(doses, list):
        raise CardError("doses must be a list")
    parsed, unrecognised = [], []
    for i, dose in enumerate(doses):
        if not isinstance(dose, dict) or not str(dose.get("antigen", "")).strip():
            raise CardError(f"dose {i + 1} needs an antigen")
        given = _parse_date(dose.get("date_given"), f"dose {i + 1} date_given")
        label = str(dose["antigen"]).strip()
        name = canonical_antigen(label)
        row = {"antigen": name or label, "date_given": given.isoformat(),
               "age_days": (given - dob).days}
        if name is None:
            unrecognised.append({**row, "reasons": [f"'{label}' is not a vaccine this engine knows; "
                                                    "check the label and add it again."]})
        else:
            if name != label:
                row["card_label"] = label
            parsed.append(row)
    parsed.sort(key=lambda d: d["age_days"])
    return parsed, unrecognised


def validate_card(dob: date, doses: list, age_today: int) -> tuple[list[dict], list[dict], list[dict]]:
    """Return (valid, invalid, unrecognised) doses, sorted by age.

    A valid dose carries ``components``: the parts it is credited for. A
    combination dose given too soon after a single-antigen dose keeps the
    parts that were on time and lists the dropped ones in ``notes``.
    """
    parsed, unrecognised = _parse_doses(dob, doses)
    valid, invalid, last_age = [], [], {}
    for dose in parsed:
        reasons = _whole_dose_reasons(dose["antigen"], dose["age_days"], age_today)
        if reasons:
            invalid.append({**dose, "reasons": reasons})
            continue
        counted, dropped = _component_check(dose["antigen"], dose["age_days"], last_age)
        if not counted:
            invalid.append({**dose, "reasons": dropped})
            continue
        valid.append({**dose, "components": counted, **({"notes": dropped} if dropped else {})})
        for comp in counted:
            last_age[comp] = dose["age_days"]
    return valid, invalid, unrecognised


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
        for comp in dose["components"]:
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
        elif slot["birth_slot"] and age_days > rules.BIRTH_DOSE_WINDOW_DAYS:
            out["missed_birth_dose"].append(slot)
        elif slot["birth_slot"]:
            out["due_now"].append(slot)
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
