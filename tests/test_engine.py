"""Engine tests. Expected results were written from the schedules before running.

Run: python3 -m unittest discover -s tests
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from hathor_core import CardError, UnknownCountry, check_card  # noqa: E402

SUDAN_CARD = [  # synthetic child, Sudan EPI schedule given on time; DOB 2025-03-01
    {"antigen": "BCG", "date_given": "2025-03-01"},
    {"antigen": "HepB", "date_given": "2025-03-01"},
    {"antigen": "OPV", "date_given": "2025-03-01"},
    *[{"antigen": a, "date_given": d}
      for d in ("2025-04-12", "2025-05-10")
      for a in ("OPV", "Pentavalent", "PCV", "Rotavirus")],
    *[{"antigen": a, "date_given": "2025-06-07"} for a in ("OPV", "Pentavalent", "PCV", "IPV")],
    {"antigen": "Measles", "date_given": "2025-12-01"},
    {"antigen": "Measles", "date_given": "2026-09-01"},
]


def _slots(result, bucket):
    return [(s["antigen"], s["dose_number"]) for s in result[bucket]]


class SudanToEgypt(unittest.TestCase):
    """A Sudanese card checked against Egypt's MoHP schedule at 20 months."""

    @classmethod
    def setUpClass(cls):
        cls.r = check_card("Egypt", "2025-03-01", SUDAN_CARD, today="2026-11-09")

    def test_summary(self):
        self.assertEqual(self.r["summary"], {
            "completed": 13, "partial": 2, "overdue": 5, "due_now": 0, "upcoming": 2,
            "aged_out": 0, "missed_birth_dose": 0, "invalid_doses": 0,
        })

    def test_measles_only_dose_leaves_mumps_rubella_open(self):
        mmr1 = self.r["partial"][0]
        self.assertEqual((mmr1["antigen"], mmr1["dose_number"]), ("MMR", 1))
        self.assertEqual(mmr1["missing_components"], ["Mumps", "Rubella"])
        self.assertEqual(mmr1["credited_from"], ["Measles"])

    def test_overdue_slots(self):
        self.assertEqual(sorted(_slots(self.r, "overdue")), sorted([
            ("OPV", 5), ("OPV", 6), ("OPV", 7), ("DTaP", 4), ("Varicella", 1)]))

    def test_pentavalent_credits_egypt_pentavalent(self):
        self.assertIn(("Pentavalent", 3), _slots(self.r, "completed"))
        self.assertIn(("IPV", 1), _slots(self.r, "completed"))

    def test_catch_up_visits(self):
        visits = {v["days_from_today"]: sorted(g["slot"] for g in v["give"])
                  for v in self.r["catch_up_visits"]}
        self.assertEqual(visits, {
            0: ["DTaP dose 4", "MMR dose 1", "OPV dose 5", "Varicella dose 1"],
            28: ["MMR dose 2", "OPV dose 6"],
            56: ["OPV dose 7"],
        })
        self.assertEqual(self.r["catch_up_visits"][0]["date"], "2026-11-09")

    def test_sources_and_disclaimer_present(self):
        self.assertIn("MoHP", self.r["schedule_source"])
        self.assertIn("paediatrician", self.r["disclaimer"])
        self.assertTrue(self.r["rule_status"]["pending_signoff"])


class EgyptOnTime(unittest.TestCase):
    def test_complete_card_has_nothing_overdue(self):
        card = [{"antigen": a, "date_given": "2025-10-01"} for a in ("HepB", "OPV")]
        card.append({"antigen": "BCG", "date_given": "2025-10-31"})
        for d, extra in (("2025-12-01", ["PCV"]), ("2026-02-01", ["IPV", "PCV"]),
                         ("2026-04-01", ["PCV"])):
            card += [{"antigen": a, "date_given": d} for a in ("Pentavalent", "OPV", *extra)]
        card.append({"antigen": "OPV", "date_given": "2026-07-01"})
        card += [{"antigen": a, "date_given": "2026-10-01"} for a in ("MMR", "OPV", "Varicella")]
        r = check_card("egypt", "2025-10-01", card, today="2026-11-01")
        self.assertEqual(r["summary"]["completed"], 17)  # every Egypt slot up to 12 months
        self.assertEqual(r["summary"]["overdue"], 0)
        self.assertEqual(r["summary"]["upcoming"], 5)
        self.assertEqual(r["catch_up_visits"], [])


class InvalidDoses(unittest.TestCase):
    def test_reasons(self):
        r = check_card("WHO", "2025-01-01", [
            {"antigen": "MMR", "date_given": "2025-06-01"},
            {"antigen": "DTaP", "date_given": "2025-02-20"},
            {"antigen": "DTaP", "date_given": "2025-03-05"},
            {"antigen": "OPV", "date_given": "2024-12-01"},
        ], today="2025-07-01")
        reasons = {d["antigen"] + d["date_given"]: " ".join(d["reasons"]) for d in r["invalid_doses"]}
        self.assertEqual(len(reasons), 3)
        self.assertIn("minimum age for MMR is 270", reasons["MMR2025-06-01"])
        self.assertIn("13 days after the previous dose", reasons["DTaP2025-03-05"])
        self.assertIn("before the date of birth", reasons["OPV2024-12-01"])


class AgeLimitsAndBirthDoses(unittest.TestCase):
    def test_rotavirus_aged_out_and_birth_doses_not_scheduled(self):
        r = check_card("WHO", "2023-01-01", [{"antigen": "BCG", "date_given": "2023-01-01"}],
                       today="2026-01-01")
        self.assertEqual(sorted(_slots(r, "aged_out")), [("Rotavirus", 1), ("Rotavirus", 2), ("Rotavirus", 3)])
        self.assertEqual(sorted(_slots(r, "missed_birth_dose")), [("HepB", 1), ("OPV", 1)])
        planned = {g["slot"] for v in r["catch_up_visits"] for g in v["give"]}
        self.assertFalse(any(s.startswith(("Rotavirus", "HepB dose 1", "OPV dose 1")) for s in planned))
        self.assertIn("HepB dose 2", planned)

    def test_late_hepb_counts_for_next_slot_not_birth(self):
        r = check_card("Egypt", "2026-01-01", [{"antigen": "HepB", "date_given": "2026-02-10"}],
                       today="2026-02-20")
        self.assertIn(("HepB", 1), _slots(r, "missed_birth_dose"))


class CatchUpSpacing(unittest.TestCase):
    def test_pcv_doses_56_days_apart(self):
        r = check_card("WHO", "2026-03-01", [], today="2026-11-01")
        pcv_days = [v["days_from_today"] for v in r["catch_up_visits"]
                    for g in v["give"] if g["slot"].startswith("PCV")]
        self.assertEqual(pcv_days, [0, 56])

    def test_no_component_twice_in_one_visit(self):
        r = check_card("Egypt", "2025-03-01", SUDAN_CARD, today="2026-11-09")
        for visit in r["catch_up_visits"]:
            comps = [c for g in visit["give"] for c in g["for_components"]]
            self.assertEqual(len(comps), len(set(comps)))


class BadInput(unittest.TestCase):
    def test_unknown_country(self):
        with self.assertRaises(UnknownCountry):
            check_card("Spain", "2025-01-01", [])

    def test_bad_date(self):
        with self.assertRaises(CardError):
            check_card("Egypt", "01/01/2025", [])

    def test_missing_antigen(self):
        with self.assertRaises(CardError):
            check_card("Egypt", "2025-01-01", [{"date_given": "2025-02-01"}])


if __name__ == "__main__":
    unittest.main()
