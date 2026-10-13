"""Exercise the installed CLI and per-case artifact layout without a live model."""

import contextlib
import copy
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from test_agent.cli import main

ROOT = Path(__file__).resolve().parents[1]


class PackageCliTests(unittest.TestCase):
    def setUp(self):
        self.fixture = json.loads((ROOT / "tests/fixtures/osm_translation.json").read_text())
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.output = Path(self.temp.name)

    def run_cli(self, plan, case="OSM-001"):
        args = ["--project-dir", str(ROOT), "translate",
                str(ROOT / "cases/osm/WBS_testcase1_osm.xlsx"),
                "--output-dir", str(self.output), "--case", case]
        with patch("test_agent.cli.translate", new=AsyncMock(return_value=json.dumps(plan))) as model, \
                patch("test_agent.cli.load_dotenv"), \
                patch.dict(os.environ, {"OPENAI_API_KEY": "fake-test-key", "OPENAI_MODEL": "fake-model"}), \
                contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            result = main(args)
        return result, model

    def test_package_entry_point_works_outside_project_directory(self):
        result = subprocess.run([sys.executable, "-m", "test_agent", "--help"],
                                cwd=self.output, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("translate", result.stdout)

    def test_translate_preserves_plan_and_writes_case_scoped_evidence(self):
        result, model = self.run_cli(self.fixture["plan"])
        self.assertEqual(result, 0)
        model.assert_awaited_once()
        folders = list(self.output.glob("translation-*/cases/OSM-001"))
        self.assertEqual(len(folders), 1)
        folder = folders[0]
        self.assertEqual(json.loads((folder / "plan.json").read_text()), self.fixture["plan"])
        report = json.loads((folder / "validation.json").read_text())
        self.assertEqual(report["status"], "VALIDATED")
        self.assertFalse(report["browser_executed"])
        source = json.loads((folder / "source.json").read_text())
        self.assertNotIn("amendments", source)
        self.assertNotIn("effective", source)
        saved_case = source["case"].copy()
        saved_case.pop("source")
        self.assertEqual(saved_case, self.fixture["case"])
        for name in ("model-output.txt", "candidate-plan.json"):
            self.assertTrue((folder / name).exists())

    def test_invalid_plan_saves_rejection_without_approved_plan(self):
        plan = copy.deepcopy(self.fixture["plan"])
        plan["steps"][4]["checks"][0]["value"] = 240
        result, _ = self.run_cli(plan)
        self.assertEqual(result, 1)
        folder = next(self.output.glob("translation-*/cases/OSM-001"))
        self.assertFalse((folder / "plan.json").exists())
        report = json.loads((folder / "validation.json").read_text())
        self.assertEqual(report["status"], "REJECTED")
        self.assertTrue(report["errors"])

    def test_missing_case_does_not_call_model(self):
        result, model = self.run_cli(self.fixture["plan"], case="OSM-999")
        self.assertEqual(result, 1)
        model.assert_not_awaited()

    def test_case_id_cannot_escape_artifact_directory(self):
        with self.assertRaises(SystemExit) as exc:
            self.run_cli(self.fixture["plan"], case="../../outside")
        self.assertEqual(exc.exception.code, 2)
        self.assertEqual(list(self.output.iterdir()), [])

    def test_removed_amendment_option_is_rejected(self):
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as exc:
            main(["translate", "cases/osm/WBS_testcase1_osm.xlsx", "--amendments", "old.json"])
        self.assertEqual(exc.exception.code, 2)
