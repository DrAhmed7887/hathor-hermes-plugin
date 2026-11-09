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
import re
import threading
import time

HATHOR_TOOLS = frozenset({"vaccine_card_check", "vaccine_schedule"})

_TOPIC = re.compile(
    r"vaccin|immuni[sz]|booster|jab|shot|\b(bcg|opv|ipv|mmr|dtap|dtp|hep ?b|pcv|rota|penta|hexa)"
    r"|تطعيم|تطعيمات|لقاح|vacuna|calendario vacunal",
    re.IGNORECASE,
)
_DOSE_CLAIM = re.compile(
    r"\b(bcg|opv|ipv|mmr|mr|dtap|dtp|dpt|td|hep ?b|hib|pcv|rota\w*|penta\w*|hexa\w*|"
    r"measles|varicella|polio|pneumococcal)\b|تطعيم|لقاح",
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

_lock = threading.Lock()
_turns: dict[str, dict] = {}  # session key -> {"started": t, "topic": bool}
_last_check = {"at": 0.0, "source": None}


def on_pre_llm_call(session_id: str = "", user_message: str = "", **kwargs):
    topic = bool(_TOPIC.search(user_message or ""))
    with _lock:
        _turns[str(session_id or "")] = {"started": time.monotonic(), "topic": topic}
        if len(_turns) > 500:
            _turns.pop(next(iter(_turns)))
    return {"context": GUIDANCE} if topic else None


def _source_of(result: str) -> str | None:
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


def on_post_tool_call(tool_name: str = "", result: str = "", task_id: str = "", **kwargs):
    if tool_name not in HATHOR_TOOLS:
        return None
    source = _source_of(result)
    if source is None:
        return None
    with _lock:
        _last_check.update(at=time.monotonic(), source=source)
    return None


def _checked_this_turn(key: str) -> str | None:
    """Source of a Hathor check that ran after this session's turn began.

    Matched by time rather than id: post_tool_call carries task_id while
    transform_llm_output carries session_id, and they may differ.
    """
    turn = _turns.get(key)
    if turn is None or _last_check["source"] is None:
        return None
    return _last_check["source"] if _last_check["at"] >= turn["started"] else None


def on_transform_llm_output(response_text: str = "", session_id: str = "", **kwargs):
    if not response_text:
        return None
    key = str(session_id or "")
    with _lock:
        turn = _turns.get(key)
        source = _checked_this_turn(key)
    if source:
        return (f"{response_text}\n\n---\n✓ Checked by Hathor against {source}. "
                "A paediatrician confirms the final plan.")
    if turn and turn["topic"] and _DOSE_CLAIM.search(response_text):
        return response_text + UNCHECKED_FOOTER
    return None


def reset_state() -> None:
    """Test helper."""
    with _lock:
        _turns.clear()
        _last_check.update(at=0.0, source=None)
