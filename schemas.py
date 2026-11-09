"""Tool schemas: what the model reads to decide when to call each tool."""

from .hathor_core import supported_countries

_COUNTRIES = ", ".join(supported_countries())

VACCINE_CARD_CHECK = {
    "name": "vaccine_card_check",
    "description": (
        "Check a child's vaccination card against a sourced national schedule "
        f"({_COUNTRIES}). Deterministic, no model guesswork: validates each dose "
        "(minimum age, maximum age, minimum interval), credits combination vaccines "
        "component by component (a Pentavalent dose covers DTP+HepB+Hib, not IPV; a "
        "measles-only dose leaves mumps and rubella open), and returns completed, "
        "partial, overdue, due-now, upcoming and aged-out slots, invalid doses with "
        "reasons, a dated catch-up visit plan, and the schedule's source. Use it "
        "whenever someone asks which vaccines a child has missed or needs next, or "
        "brings a card from one country to another. Always pass dates as YYYY-MM-DD."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "country": {
                "type": "string",
                "description": f"Schedule to check against: {_COUNTRIES}.",
            },
            "date_of_birth": {"type": "string", "description": "Child's date of birth, YYYY-MM-DD."},
            "doses": {
                "type": "array",
                "description": "Every dose written on the card, one entry per vaccine given.",
                "items": {
                    "type": "object",
                    "properties": {
                        "antigen": {
                            "type": "string",
                            "description": (
                                "Vaccine as written, normalised to one of: BCG, HepB, OPV, IPV, "
                                "Pentavalent, Hexavalent, DTaP, DT, Td, Hib, PCV, Rotavirus, "
                                "Measles, MR, MMR, Varicella, YellowFever, MenA, HPV."
                            ),
                        },
                        "date_given": {"type": "string", "description": "YYYY-MM-DD."},
                    },
                    "required": ["antigen", "date_given"],
                },
            },
            "today": {
                "type": "string",
                "description": "Optional check date, YYYY-MM-DD. Defaults to today.",
            },
        },
        "required": ["country", "date_of_birth", "doses"],
    },
}

VACCINE_SCHEDULE = {
    "name": "vaccine_schedule",
    "description": (
        f"Return a country's routine childhood vaccination schedule ({_COUNTRIES}) "
        "with the recommended age of every dose and the official source it came from."
    ),
    "parameters": {
        "type": "object",
        "properties": {"country": {"type": "string", "description": f"One of: {_COUNTRIES}."}},
        "required": ["country"],
    },
}
