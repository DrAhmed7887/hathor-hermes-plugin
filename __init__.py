"""Hathor catch-up: a Hermes Agent plugin for cross-border vaccine cards."""

from __future__ import annotations

import logging
from pathlib import Path

from . import guard, schemas, tools

logger = logging.getLogger(__name__)

TOOLSET = "hathor"


def register(ctx):
    ctx.register_tool(name="vaccine_card_check", toolset=TOOLSET,
                      schema=schemas.VACCINE_CARD_CHECK, handler=tools.vaccine_card_check)
    ctx.register_tool(name="vaccine_schedule", toolset=TOOLSET,
                      schema=schemas.VACCINE_SCHEDULE, handler=tools.vaccine_schedule)

    ctx.register_hook("pre_llm_call", guard.on_pre_llm_call)
    ctx.register_hook("post_tool_call", guard.on_post_tool_call)
    ctx.register_hook("transform_llm_output", guard.on_transform_llm_output)

    register_skill = getattr(ctx, "register_skill", None)
    skill_md = Path(__file__).parent / "skills" / "vaccine-catchup" / "SKILL.md"
    if register_skill is None:
        logger.info("hathor-catchup: this Hermes has no register_skill; skill not bundled")
    elif skill_md.exists():
        register_skill("vaccine-catchup", skill_md)
    else:
        logger.warning("hathor-catchup: bundled skill missing at %s", skill_md)
