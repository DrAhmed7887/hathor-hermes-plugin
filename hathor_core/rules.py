"""Clinical rule tables for the Hathor catch-up engine.

Every table here is a clinical rule. Rows marked ``SIGNED_HATHOR`` come
unchanged from the Hathor engine (github.com/DrAhmed7887/hathor, api/src/
hathor/tools/*.py). Rows marked ``PENDING_SIGNOFF`` are new in this plugin
and must be reviewed by the physician owner before they are described as
signed in any public material. ``RULE_STATUS`` is exported so tools can
report it.
"""

from __future__ import annotations

SIGNED_HATHOR = "hathor-engine-2026-05"
PENDING_SIGNOFF = "pending-physician-signoff"

# Combination products -> the components one dose supplies.
# PENDING_SIGNOFF: Hathor tracked the DPT triple as one "DPT" token. This
# plugin splits it into Diphtheria / Tetanus / Pertussis so that a DT or Td
# school booster can be credited from the 5th diphtheria-containing dose,
# and adds WHO's MCV/RCV labels.
COMPONENTS: dict[str, tuple[str, ...]] = {
    "Pentavalent": ("Diphtheria", "Tetanus", "Pertussis", "HepB", "Hib"),
    "Penta": ("Diphtheria", "Tetanus", "Pertussis", "HepB", "Hib"),
    "DTP-HepB-Hib": ("Diphtheria", "Tetanus", "Pertussis", "HepB", "Hib"),
    "Hexavalent": ("Diphtheria", "Tetanus", "Pertussis", "HepB", "Hib", "IPV"),
    "DTP-HepB-Hib-IPV": ("Diphtheria", "Tetanus", "Pertussis", "HepB", "Hib", "IPV"),
    "Pentaxim": ("Diphtheria", "Tetanus", "Pertussis", "Hib", "IPV"),
    "DTaP": ("Diphtheria", "Tetanus", "Pertussis"),
    "DTPw": ("Diphtheria", "Tetanus", "Pertussis"),
    "DPT": ("Diphtheria", "Tetanus", "Pertussis"),
    "Tdap": ("Diphtheria", "Tetanus", "Pertussis"),
    "DT": ("Diphtheria", "Tetanus"),
    "Td": ("Diphtheria", "Tetanus"),
    "MMR": ("Measles", "Mumps", "Rubella"),
    "MR": ("Measles", "Rubella"),
    "MMRV": ("Measles", "Mumps", "Rubella", "Varicella"),
    "MCV": ("Measles",),
    "RCV": ("Rubella",),
}

# Minimum age (days) for a dose to count. SIGNED_HATHOR (dose_validation.py),
# plus PENDING_SIGNOFF rows for combination labels Hathor validated via DPT.
MIN_AGE_DAYS: dict[str, int] = {
    "DTaP": 42, "DPT": 42, "DTPw": 42, "HepB": 0, "Hib": 42, "IPV": 42,
    "OPV": 0, "PCV": 42, "MMR": 270, "Measles": 180, "Rubella": 270,
    "Varicella": 270, "Rotavirus": 42, "BCG": 0, "HepA": 365,
    "DT": 1460, "Td": 2555,
    # PENDING_SIGNOFF
    "Pentavalent": 42, "Penta": 42, "Hexavalent": 42, "Pentaxim": 42,
    "MCV": 180, "RCV": 270, "MR": 270, "MMRV": 270,
}
DEFAULT_MIN_AGE_DAYS = 42

# Age after which a missing dose is no longer given. SIGNED_HATHOR.
MAX_AGE_DAYS: dict[str, int] = {"Rotavirus": 730, "Hib": 1825}

# Minimum days between consecutive doses of the same component.
# SIGNED_HATHOR (intervals.py: 28 days for every listed antigen).
MIN_INTERVAL_DAYS = 28

# Minimum spacing between catch-up visits, by slot antigen. SIGNED_HATHOR
# (catchup.py).
CATCHUP_MIN_INTERVALS: dict[str, int] = {
    "DTaP": 28, "DPT": 28, "HepB": 28, "Hib": 28, "IPV": 28, "PCV": 56,
    "MMR": 28, "Varicella": 84, "Rotavirus": 28, "OPV": 28,
}
DEFAULT_CATCHUP_INTERVAL = 28

LIVE_VACCINES = frozenset({"MMR", "MR", "MMRV", "MCV", "RCV", "Measles",
                           "Varicella", "Rotavirus", "OPV", "BCG", "YellowFever"})

# Window (months) around the recommended age in which a slot is "due now".
# SIGNED_HATHOR (coverage.py DUE_NOW_WINDOW).
DUE_NOW_WINDOW_MONTHS = 2

DAYS_PER_MONTH = 30.4375

# A birth-dose slot (HepB-0, OPV-0) is credited only by a dose given within
# the neonatal period. A missed birth dose is reported, never scheduled late:
# the later primary series still runs. PENDING_SIGNOFF (window value).
BIRTH_DOSE_ANTIGENS = frozenset({"HepB", "OPV"})
BIRTH_DOSE_WINDOW_DAYS = 28

RULE_STATUS = {
    "signed": SIGNED_HATHOR,
    "pending_signoff": [
        "DPT split into Diphtheria/Tetanus/Pertussis components",
        "WHO MCV/RCV labels mapped to Measles/Rubella",
        "Minimum ages for Pentavalent/Hexavalent/Pentaxim (42 d), MCV (180 d), RCV/MR/MMRV (270 d)",
        "Doses credited in order per component instead of by dose number",
        "Birth-dose slots (HepB-0, OPV-0) credited only within 28 days of birth; missed ones are reported, not scheduled",
    ],
}


def components_for(antigen: str) -> tuple[str, ...]:
    """Components one dose of ``antigen`` supplies (itself if single)."""
    return COMPONENTS.get(antigen, (antigen,))
