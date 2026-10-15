"""No model/browser calls, new artifacts only, current constraints remain enforced."""
import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from test_executor import ROOT, translation_folder
from test_agent.cli import main
from test_agent.plan_loader import load_plan


class RevalidateTests(unittest.TestCase):
    def invoke(self, folder, root):
        with contextlib.redirect_stdout(io.StringIO()) as output, patch("test_agent.cli.translate") as model:
            code = main(["--project-dir",str(ROOT),"revalidate",str(folder),"--output-dir",str(root)])
        model.assert_not_called()
        return code, json.loads(output.getvalue())

    def test_contract_only_change_new_validated_folder_old_untouched(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp); folder=translation_folder(root)
            original={p.name:p.read_bytes() for p in folder.iterdir()}
            source=json.loads((folder / "source.json").read_text())
            current=source["contract"]
            current["vision_checks"]=[dict(step=4,kind="route_geometry",requirement="Continuous Hamburg to Berlin route.",min_confidence=0.90)]
            Path(source["contract_file"]).write_text(json.dumps({"OSM-001":current}))
            code,report=self.invoke(folder,root)
            self.assertEqual(code,0)
            new=Path(report["output_directory"])
            self.assertNotEqual(new,folder)
            plan,loaded=load_plan(new)
            self.assertEqual(loaded["contract"]["vision_checks"][0]["min_confidence"],0.90)
            self.assertEqual(loaded["revalidated_from"],str(folder.resolve()))
            self.assertEqual(original,{p.name:p.read_bytes() for p in folder.iterdir()})

    def test_workbook_change_rejected_without_approved_plan(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp); folder=translation_folder(root)
            current=json.loads((folder / "source.json").read_text())["case"]
            current["expected"][4]["text"]="Under four hours"
            with patch("test_agent.plan_loader.read_case",return_value=current):
                code,report=self.invoke(folder,root)
            self.assertEqual(code,1)
            self.assertEqual(report["status"],"REJECTED")
            self.assertIn("Workbook requirements changed",report["errors"][0])
            self.assertFalse((Path(report["output_directory"]) / "plan.json").exists())

    def test_modified_plan_still_rejected_against_current_contract(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp); folder=translation_folder(root)
            plan=json.loads((folder / "plan.json").read_text())
            plan["steps"][4]["checks"][0]["value"]=240
            (folder / "plan.json").write_text(json.dumps(plan))
            code,report=self.invoke(folder,root)
            self.assertEqual(code,1)
            self.assertFalse((Path(report["output_directory"]) / "plan.json").exists())
