"""Tool handlers. Each returns a JSON string and never raises."""

from __future__ import annotations

import json
import logging

from .hathor_core import CardError, UnknownCountry, check_card, load_schedule

logger = logging.getLogger(__name__)


def _error(message: str) -> str:
    return json.dumps({"error": message})


def vaccine_card_check(args: dict, **kwargs) -> str:
    if not isinstance(args, dict):
        return _error("arguments must be an object")
    try:
        result = check_card(
            country=args.get("country", ""),
            date_of_birth=args.get("date_of_birth", ""),
            doses=args.get("doses", []),
            today=args.get("today") or None,
        )
        return json.dumps(result, ensure_ascii=False)
    except (CardError, UnknownCountry) as exc:
        return _error(str(exc))
    except Exception:  # never crash the agent loop
        logger.exception("vaccine_card_check failed")
        return _error("internal error while checking the card")


def vaccine_schedule(args: dict, **kwargs) -> str:
    if not isinstance(args, dict):
        return _error("arguments must be an object")
    try:
        schedule = load_schedule(args.get("country", ""))
    except UnknownCountry as exc:
        return _error(str(exc))
    except Exception:
        logger.exception("vaccine_schedule failed")
        return _error("internal error while loading the schedule")
    rows = [{
        "antigen": d["antigen"],
        "dose_number": d.get("dose_number"),
        "recommended_age_months": d.get("recommended_age_months"),
        "category": d.get("category", "compulsory"),
    } for d in schedule["doses"]]
    return json.dumps({
        "country": schedule["country"],
        "source": schedule["source"],
        "source_urls": schedule["source_urls"],
        "last_updated": schedule["last_updated"],
        "doses": rows,
    }, ensure_ascii=False)
