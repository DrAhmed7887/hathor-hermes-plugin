"""Load the sourced national schedules shipped in data/schedules/."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from .rules import DAYS_PER_MONTH

SCHEDULES_DIR = Path(__file__).resolve().parent.parent / "data" / "schedules"

_ALIASES = {
    "egypt": "egypt", "eg": "egypt", "egy": "egypt", "مصر": "egypt",
    "sudan": "sudan", "sd": "sudan", "sdn": "sudan", "السودان": "sudan",
    "syria": "syria", "sy": "syria", "syr": "syria", "سوريا": "syria",
    "nigeria": "nigeria", "ng": "nigeria", "nga": "nigeria",
    "ethiopia": "ethiopia", "et": "ethiopia", "eth": "ethiopia",
    "eritrea": "eritrea", "er": "eritrea", "eri": "eritrea",
    "south sudan": "south_sudan", "south_sudan": "south_sudan", "ss": "south_sudan",
    "ssd": "south_sudan",
    "who": "who", "world health organization": "who",
}


class UnknownCountry(ValueError):
    """Raised when no shipped schedule matches the requested country."""


def supported_countries() -> list[str]:
    return sorted(p.stem for p in SCHEDULES_DIR.glob("*.json"))


def _key(country: str) -> str:
    if not isinstance(country, str) or not country.strip():
        raise UnknownCountry("country is required")
    key = _ALIASES.get(country.strip().lower())
    if key is None:
        raise UnknownCountry(
            f"No schedule for '{country}'. Supported: {', '.join(supported_countries())}"
        )
    return key


def _months(dose: dict, field: str) -> float | None:
    """Return an age field in months, deriving it from weeks or years."""
    value = dose.get(f"{field}_months")
    if isinstance(value, (int, float)):
        return float(value)
    weeks = dose.get(f"{field}_weeks")
    if isinstance(weeks, (int, float)):
        return round(float(weeks) * 7 / DAYS_PER_MONTH, 2)
    years = dose.get(f"{field}_years")
    if isinstance(years, (int, float)):
        return float(years) * 12
    return None


@lru_cache(maxsize=None)
def _load_raw(key: str) -> dict:
    with open(SCHEDULES_DIR / f"{key}.json", encoding="utf-8") as fh:
        return json.load(fh)


def load_schedule(country: str) -> dict:
    """Return a schedule with every dose's ages normalised to months."""
    raw = _load_raw(_key(country))
    doses = []
    for dose in raw.get("doses", []):
        rec = _months(dose, "recommended_age")
        minimum = _months(dose, "minimum_age")
        doses.append({
            **dose,
            "recommended_age_months": rec,
            "minimum_age_months": minimum if minimum is not None else rec,
        })
    return {
        "key": _key(country),
        "country": raw.get("country"),
        "source": raw.get("source"),
        "source_urls": raw.get("source_urls") or ([raw["source_url"]] if raw.get("source_url") else []),
        "last_updated": raw.get("last_updated"),
        "doses": doses,
    }
