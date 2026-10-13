"""Regression checks for translation mistakes, with no API/browser calls."""

import copy
import json
import unittest
from pathlib import Path

from pydantic import ValidationError

from test_agent.readers.excel import numbered_items, read_case
from test_agent.schemas.plan import TranslationPlan
from test_agent.translation.validator import validate_plan

ROOT = Path(__file__).resolve().parents[1]


class TranslationValidationTests(unittest.TestCase):
    def setUp(self):
        fixture = json.loads((ROOT / "tests/fixtures/osm_translation.json").read_text())
        self.case = fixture["case"]
        self.candidate = copy.deepcopy(fixture["plan"])
        self.contract = json.loads((ROOT / "cases/osm/contracts.json").read_text())["OSM-001"]

    def errors(self):
        return validate_plan(TranslationPlan.model_validate(self.candidate), self.case,
                             "https://www.openstreetmap.org/", self.contract)

    def test_valid_translation_and_nonblocking_notes(self):
        self.candidate["notes"] = ["Observation-only step requires no browser action."]
        self.assertEqual(self.errors(), [])

    def test_duration_limit_cannot_be_relaxed_or_tightened(self):
        for limit in (179, 240):
            with self.subTest(limit=limit):
                self.candidate["steps"][4]["checks"][0]["value"] = limit
                self.assertTrue(any("Duration" in error for error in self.errors()))

    def test_inclusive_duration_is_rejected(self):
        self.candidate["steps"][4]["checks"][0]["operator"] = "less_than_or_equal"
        with self.assertRaises(ValidationError):
            TranslationPlan.model_validate(self.candidate)

    def test_wrong_city_is_rejected(self):
        self.candidate["steps"][3]["actions"][1]["value"] = "Bremen"
        self.assertTrue(any("Berlin" in error for error in self.errors()))

    def test_submit_before_fill_is_rejected(self):
        actions = self.candidate["steps"][3]["actions"]
        actions.insert(0, actions.pop())
        self.assertTrue(any("after filling" in error for error in self.errors()))

    def test_swapped_origin_destination_is_rejected(self):
        actions = self.candidate["steps"][3]["actions"]
        actions[0]["value"], actions[1]["value"] = actions[1]["value"], actions[0]["value"]
        self.assertTrue(any("must receive" in error for error in self.errors()))

    def test_missing_cleanup_field_is_rejected(self):
        self.candidate["cleanup"].pop()
        self.assertTrue(any("Cleanup must clear" in error for error in self.errors()))

    def test_missing_step_is_rejected(self):
        self.candidate["steps"].pop(1)
        self.assertTrue(any("Source steps" in error for error in self.errors()))

    def test_rewritten_source_is_rejected(self):
        self.candidate["steps"][0]["source_action"] = "Open another application"
        self.assertTrue(any("wording changed" in error for error in self.errors()))

    def test_missing_field_check_is_rejected(self):
        self.candidate["steps"][1]["checks"].pop()
        self.assertTrue(any("visibility check" in error for error in self.errors()))

    def test_comparator_cannot_replace_expected_driving_mode(self):
        self.candidate["steps"][2]["checks"][0]["value"] = "equals"
        self.assertTrue(any("Travel-mode check" in error for error in self.errors()))

    def test_arbitrary_code_action_is_rejected(self):
        self.candidate["steps"][0]["actions"][0]["action"] = "execute_python"
        with self.assertRaises(ValidationError):
            TranslationPlan.model_validate(self.candidate)

    def test_model_cannot_claim_test_pass(self):
        self.candidate["status"] = "PASS"
        with self.assertRaises(ValidationError):
            TranslationPlan.model_validate(self.candidate)

    def test_unresolved_issue_blocks_plan(self):
        self.candidate["issues"] = ["Unspecified destination"]
        self.assertTrue(any("needs clarification" in error for error in self.errors()))

    def test_unnumbered_and_duplicate_steps_rejected(self):
        for text in ("Open OSM", "1. Open OSM\n1. Click directions", "1. Open OSM\n3. Click directions"):
            with self.subTest(text=text), self.assertRaises(ValueError):
                numbered_items(text)

    def test_workbook_requirements_match_reviewed_reference(self):
        case = read_case(ROOT / "cases/osm/WBS_testcase1_osm.xlsx", "OSM-001")
        case.pop("source")
        self.assertEqual(case, self.case)


if __name__ == "__main__":
    unittest.main()
