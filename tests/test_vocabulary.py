"""Vocabulary input reaches the model, and remains independent of DOM mappings."""

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from test_agent.schemas.vocabulary import TargetVocabulary
from test_agent.translation.translator import INSTRUCTIONS, translate
from test_agent.translation.validator import validate_plan
from test_agent.schemas.plan import TranslationPlan
from test_agent.plan_loader import load_plan
from test_executor import translation_folder

ROOT = Path(__file__).resolve().parents[1]


class VocabularyTests(unittest.IsolatedAsyncioTestCase):
    async def test_translator_receives_suite_catalog_and_hints(self):
        vocabulary = json.loads((ROOT / "cases/osm/vocabulary.json").read_text())
        with patch("test_agent.translation.translator.Runner.run", new=AsyncMock(
                return_value=SimpleNamespace(final_output='{}'))) as run:
            await translate({}, "https://example.test/", api_key="fake", model_name="fake",
                            base_url="https://example.test/v1", vocabulary=vocabulary)
        payload = json.loads(run.call_args.args[1])
        self.assertEqual(payload["vocabulary"], vocabulary)
        self.assertNotIn("For OSM", INSTRUCTIONS)
        self.assertNotIn("value='Car'", INSTRUCTIONS)

    async def test_declared_targets_do_not_require_existing_locators(self):
        fixture = json.loads((ROOT / "tests/fixtures/osm_translation.json").read_text())
        plan = TranslationPlan.model_validate(fixture["plan"])
        names = {item.target for step in plan.steps for item in [*step.actions, *step.checks]}
        names.update(item.target for item in plan.cleanup)
        vocabulary = TargetVocabulary(targets={name: "Declared semantic target" for name in names})
        self.assertEqual(validate_plan(plan, fixture["case"], "https://www.openstreetmap.org/",
                                       known_targets=set(vocabulary.targets)), [])

    async def test_loader_rejects_changed_vocabulary_and_unknown_saved_target(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = translation_folder(Path(temp))
            path = Path(temp) / "vocabulary.json"
            vocabulary = json.loads((ROOT / "cases/osm/vocabulary.json").read_text())
            path.write_text(json.dumps(vocabulary))
            source = json.loads((folder / "source.json").read_text())
            source.update(vocabulary=vocabulary, vocabulary_file=str(path))
            (folder / "source.json").write_text(json.dumps(source))
            load_plan(folder)
            plan = json.loads((folder / "plan.json").read_text())
            plan["steps"][4]["checks"][0]["target"] = "route duration"
            (folder / "plan.json").write_text(json.dumps(plan))
            with self.assertRaisesRegex(ValueError, "UNKNOWN_TARGET"):
                load_plan(folder)
            vocabulary["hints"].append("New suite requirement")
            path.write_text(json.dumps(vocabulary))
            with self.assertRaisesRegex(ValueError, "Target vocabulary changed"):
                load_plan(folder)
