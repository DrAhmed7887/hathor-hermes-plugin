"""The schedule guard: vaccine answers must come from the tool, not memory.

Three hooks work together:
- ``pre_llm_call`` spots a vaccine question (English, Arabic, Spanish) and
  tells the model to use ``vaccine_card_check`` instead of recalling doses.
- ``post_tool_call`` records that a Hathor tool ran, and which source it used.
- ``transform_llm_output`` adds one footer to the final reply: the source
  when the answer was checked, or a plain warning when a reply names
  vaccine doses without any check. No extra model calls.
"""

from __future__ import annotations

import json
import logging
import re
import threading
import time

HATHOR_TOOLS = frozenset({"vaccine_card_check", "vaccine_schedule"})

_TOPIC = re.compile(
    r"\b(vaccin\w*|immuni[sz]\w*|bcg|opv|ipv|mmr|dtap|dtp|hep ?b|pcv"
    r"|rota(virus)?|penta(valent)?|hexa(valent)?|polio|measles)\b"
    r"|تطعيم|تطعيمات|لقاح|vacuna|calendario vacunal",
    re.IGNORECASE,
)
# Everyday words that mean a vaccine only next to a child or "due/need" word.
_SOFT = re.compile(r"\b(jabs?|shots?|boosters?)\b", re.IGNORECASE)
_SOFT_CONTEXT = re.compile(
    r"\b(baby|babies|child|children|kids?|son|daughter|toddler|infant|newborn|need|needs|due|missed?)\b",
    re.IGNORECASE,
)
_DOSE_CLAIM = re.compile(
    r"\b(bcg|opv|ipv|mmr|mr|dtap|dtp|dpt|td|hep ?b|hib|pcv|rota(virus)?|penta(valent)?"
    r"|hexa(valent)?|measles|varicella|polio|pneumococcal)\b|تطعيم|لقاح",
    re.IGNORECASE,
)

GUIDANCE = (
    "[Hathor] This turn is about childhood vaccines. To say which doses a child has "
    "missed, needs now or needs next, call vaccine_card_check with the card's dates; "
    "do not list doses from memory. Quote the schedule source it returns and say "
    "that a paediatrician confirms the plan."
)
UNCHECKED_FOOTER = (
    "\n\n---\n⚠️ Hathor: this answer names vaccine doses but was not checked against a "
    "sourced schedule. Share the card (date of birth and each dose date) to check it."
)
MAX_SESSIONS = 500

_lock = threading.Lock()
_turns: dict[str, dict] = {}   # session_id -> {"started": t, "topic": bool}
_checks: dict[str, tuple[float, str]] = {}  # session or task id -> (time, source)
_last_check: dict = {"at": 0.0, "source": None, "keys": frozenset()}

logger = logging.getLogger(__name__)


def _text(value) -> str:
    """Hook payloads can be lists (multimodal) or None; only plain text is read."""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return " ".join(p.get("text", "") if isinstance(p, dict) else str(p) for p in value
                        if isinstance(p, (dict, str)))
    return ""


def _remember(store: dict, key: str, value) -> None:
    store.pop(key, None)  # re-insert so the dict stays in recent-use order
    store[key] = value
    while len(store) > MAX_SESSIONS:
        store.pop(next(iter(store)))


def on_pre_llm_call(session_id: str = "", user_message="", **kwargs):
    try:
        text = _text(user_message)
        topic = bool(_TOPIC.search(text) or (_SOFT.search(text) and _SOFT_CONTEXT.search(text)))
        with _lock:
            _remember(_turns, str(session_id or ""), {"started": time.monotonic(), "topic": topic})
        return {"context": GUIDANCE} if topic else None
    except Exception:
        logger.exception("hathor guard: pre_llm_call failed")
        return None


def _source_of(result) -> str | None:
    try:
        data = json.loads(result)
    except (TypeError, ValueError):
        return None
    if not isinstance(data, dict) or "error" in data:
        return None
    country = data.get("country") or "the schedule"
    source = data.get("schedule_source") or data.get("source") or "its official source"
    updated = data.get("schedule_last_updated") or data.get("last_updated")
    return f"{country}: {source}" + (f" (last updated {updated})" if updated else "")


def on_post_tool_call(tool_name: str = "", result="", task_id: str = "", **kwargs):
    try:
        if tool_name not in HATHOR_TOOLS:
            return None
        source = _source_of(result)
        if source is None:
            return None
        now = time.monotonic()
        keys = frozenset(k for k in (str(task_id or ""), str(kwargs.get("session_id") or "")) if k)
        with _lock:
            for key in keys:
                _remember(_checks, key, (now, source))
            _last_check.update(at=now, source=source, keys=keys)
    except Exception:
        logger.exception("hathor guard: post_tool_call failed")
    return None


def _checked_this_turn(key: str) -> str | None:
    """Source of a Hathor check that ran in this session after its turn began.

    Matched by id when post_tool_call's ids include this session. If the
    check's ids match no known session (Hermes passed a task id that differs
    from the session id), fall back to time: the last check counts for the
    session whose turn it followed.
    """
    turn = _turns.get(key)
    if turn is None:
        return None
    hit = _checks.get(key)
    if hit is not None:
        return hit[1] if hit[0] >= turn["started"] else None
    orphan = _last_check["source"] and not (_last_check["keys"] & set(_turns))
    if orphan and _last_check["at"] >= turn["started"]:
        return _last_check["source"]
    return None


def on_transform_llm_output(response_text="", session_id: str = "", **kwargs):
    try:
        text = response_text if isinstance(response_text, str) else ""
        if not text:
            return None
        key = str(session_id or "")
        with _lock:
            turn = _turns.get(key)
            source = _checked_this_turn(key)
        if source:
            return (f"{text}\n\n---\n✓ Checked by Hathor against {source}. "
                    "A paediatrician confirms the final plan.")
        if turn and turn["topic"] and _DOSE_CLAIM.search(text):
            return text + UNCHECKED_FOOTER
    except Exception:
        logger.exception("hathor guard: transform_llm_output failed")
    return None


def reset_state() -> None:
    """Test helper."""
    with _lock:
        _turns.clear()
        _checks.clear()
        _last_check.update(at=0.0, source=None, keys=frozenset())
