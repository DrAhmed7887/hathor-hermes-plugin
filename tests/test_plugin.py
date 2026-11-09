"""Plugin-layer tests: registration, handlers and the schedule guard.

The plugin directory is loaded as a package the way Hermes loads it (by its
__init__.py), with a fake ctx that records what register() asks for.
"""

import importlib.util
import json
import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import yaml_free_manifest as manifest  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent


def _load_plugin():
    spec = importlib.util.spec_from_file_location(
        "hathor_catchup", ROOT / "__init__.py", submodule_search_locations=[str(ROOT)])
    module = importlib.util.module_from_spec(spec)
    sys.modules["hathor_catchup"] = module
    spec.loader.exec_module(module)
    return module


PLUGIN = _load_plugin()
from hathor_catchup import guard, tools  # noqa: E402


class FakeCtx:
    def __init__(self):
        self.tools, self.hooks, self.skills = {}, {}, {}

    def register_tool(self, name, toolset, schema, handler, **kwargs):
        self.tools[name] = (toolset, schema, handler)

    def register_hook(self, name, callback, **kwargs):
        self.hooks[name] = callback

    def register_skill(self, name, path):
        self.skills[name] = Path(path)


class Registration(unittest.TestCase):
    def setUp(self):
        self.ctx = FakeCtx()
        PLUGIN.register(self.ctx)

    def test_registers_what_the_manifest_declares(self):
        declared = manifest.read(ROOT / "plugin.yaml")
        self.assertEqual(sorted(self.ctx.tools), sorted(declared["provides_tools"]))
        self.assertEqual(sorted(self.ctx.hooks), sorted(declared["provides_hooks"]))

    def test_schema_names_match(self):
        for name, (_, schema, _) in self.ctx.tools.items():
            self.assertEqual(schema["name"], name)

    def test_skill_bundled(self):
        self.assertTrue(self.ctx.skills["vaccine-catchup"].exists())


class Handlers(unittest.TestCase):
    def test_check_returns_json(self):
        out = json.loads(tools.vaccine_card_check({
            "country": "WHO", "date_of_birth": "2026-01-01", "today": "2026-03-01",
            "doses": [{"antigen": "BCG", "date_given": "2026-01-01"}]}))
        self.assertIn("catch_up_visits", out)

    def test_errors_are_json_not_exceptions(self):
        for args in ({"country": "Spain", "date_of_birth": "2026-01-01", "doses": []},
                     {"country": "Egypt", "date_of_birth": "nope", "doses": []},
                     {"country": "Egypt", "date_of_birth": "2026-01-01", "doses": "x"},
                     "not a dict"):
            self.assertIn("error", json.loads(tools.vaccine_card_check(args)))

    def test_schedule_has_source(self):
        out = json.loads(tools.vaccine_schedule({"country": "sudan"}))
        self.assertTrue(out["source"])
        self.assertTrue(all(d["recommended_age_months"] is not None for d in out["doses"]))


class Guard(unittest.TestCase):
    def setUp(self):
        guard.reset_state()

    def test_injects_guidance_only_for_vaccine_questions(self):
        self.assertIsNotNone(guard.on_pre_llm_call(session_id="s", user_message="What jabs does she need?"))
        self.assertIsNotNone(guard.on_pre_llm_call(session_id="s", user_message="ما هي التطعيمات الناقصة؟"))
        self.assertIsNone(guard.on_pre_llm_call(session_id="s", user_message="Book a table for two"))

    def test_unchecked_dose_answer_gets_warning(self):
        guard.on_pre_llm_call(session_id="s", user_message="what vaccines are due at 18 months?")
        out = guard.on_transform_llm_output(response_text="She needs MMR and DTaP now.", session_id="s")
        self.assertIn("not checked against a sourced schedule", out)

    def test_checked_answer_gets_source_footer(self):
        guard.on_pre_llm_call(session_id="s", user_message="check this vaccine card")
        time.sleep(0.001)
        result = tools.vaccine_card_check({"country": "Egypt", "date_of_birth": "2026-01-01",
                                           "today": "2026-03-01", "doses": []})
        guard.on_post_tool_call(tool_name="vaccine_card_check", result=result, task_id="t")
        out = guard.on_transform_llm_output(response_text="Here is the plan: MMR later.", session_id="s")
        self.assertIn("Checked by Hathor against Egypt", out)
        self.assertNotIn("not checked", out)

    def test_old_check_does_not_cover_a_new_turn(self):
        result = tools.vaccine_schedule({"country": "WHO"})
        guard.on_post_tool_call(tool_name="vaccine_schedule", result=result, task_id="t")
        time.sleep(0.001)
        guard.on_pre_llm_call(session_id="s", user_message="what about the polio vaccine?")
        out = guard.on_transform_llm_output(response_text="Give OPV now.", session_id="s")
        self.assertIn("not checked", out)

    def test_failed_tool_call_does_not_count_as_checked(self):
        guard.on_pre_llm_call(session_id="s", user_message="vaccines for my son")
        guard.on_post_tool_call(tool_name="vaccine_card_check", result='{"error": "x"}', task_id="t")
        out = guard.on_transform_llm_output(response_text="He needs PCV.", session_id="s")
        self.assertIn("not checked", out)

    def test_other_sessions_check_does_not_vouch_for_this_one(self):
        guard.on_pre_llm_call(session_id="A", user_message="vaccines for my son")
        result = tools.vaccine_schedule({"country": "WHO"})
        guard.on_post_tool_call(tool_name="vaccine_schedule", result=result, task_id="B",
                                session_id="B")
        guard.on_pre_llm_call(session_id="B", user_message="vaccine schedule please")
        out = guard.on_transform_llm_output(response_text="He needs PCV.", session_id="A")
        self.assertIn("not checked", out)

    def test_hooks_never_raise_on_odd_payloads(self):
        self.assertIsNone(guard.on_pre_llm_call(session_id="s", user_message=[{"type": "image"}]))
        self.assertIsNotNone(guard.on_pre_llm_call(session_id="s",
                                                   user_message=[{"type": "text", "text": "vaccine card"}]))
        self.assertIsNone(guard.on_transform_llm_output(response_text=["x"], session_id="s"))
        self.assertIsNone(guard.on_post_tool_call(tool_name="vaccine_card_check", result=None))

    def test_topic_needs_whole_words(self):
        for text in ("I shot a photo", "rotate the image", "pentagon shape", "a booster seat"):
            self.assertIsNone(guard.on_pre_llm_call(session_id="s", user_message=text), text)

    def test_unrelated_reply_untouched(self):
        guard.on_pre_llm_call(session_id="s", user_message="Book a table for two")
        self.assertIsNone(guard.on_transform_llm_output(response_text="Done.", session_id="s"))


if __name__ == "__main__":
    unittest.main()
