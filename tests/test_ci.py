"""CI result classification, independently of Jenkins and live providers."""
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from browser_support import chromium_available

spec=importlib.util.spec_from_file_location('suite_result',Path(__file__).resolve().parents[1]/'ci/suite_result.py')
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)


class CIResultTests(unittest.TestCase):
    def test_browser_detection_respects_configured_path(self):
        with tempfile.TemporaryDirectory() as temp,patch.dict('os.environ',{'PLAYWRIGHT_BROWSERS_PATH':temp}):
            self.assertFalse(chromium_available())
            binary=Path(temp)/'chromium_headless_shell/linux/chrome-headless-shell'
            binary.parent.mkdir(parents=True);binary.write_text('fixture')
            self.assertTrue(chromium_available())

    def test_completed_test_outcomes_are_distinct_from_infrastructure_errors(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);folder=root/'suite-one';folder.mkdir()
            summary=dict(status='PASSED',cases=[dict(status='PASSED')],duration_seconds=1,reason=None)
            for name in ['audit.csv','report.html']:(folder/name).write_text('fixture')
            def save(): (folder/'summary.json').write_text(json.dumps(summary))
            save();self.assertEqual(module.build_result(0,root),'SUCCESS')
            self.assertEqual(module.build_result(1,root),'FAILURE')
            for status in ['FAILED','BLOCKED']:
                summary.update(status=status,cases=[dict(status=status)]);save()
                self.assertEqual(module.build_result(1,root),'UNSTABLE')
                self.assertEqual(module.build_result(0,root),'FAILURE')
            for code in [2,3,137,-9]:self.assertEqual(module.build_result(code,root),'FAILURE')
            summary['reason']='SUITE_INPUT: invalid workbook';save()
            self.assertEqual(module.build_result(1,root),'FAILURE')

    def test_crash_missing_partial_or_malformed_evidence_is_failure(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            self.assertEqual(module.build_result(1,root),'FAILURE')
            folder=root/'suite-one';folder.mkdir()
            path=folder/'summary.json';path.write_text('{bad json')
            self.assertEqual(module.build_result(1,root),'FAILURE')
            path.write_text(json.dumps(dict(status='BLOCKED',cases=[dict(status='BLOCKED')],duration_seconds=1)))
            self.assertEqual(module.build_result(1,root),'FAILURE')
            for name in ['audit.csv','report.html']:(folder/name).write_text('fixture')
            self.assertEqual(module.build_result(1,root),'UNSTABLE')
            (root/'suite-stale').mkdir()
            self.assertEqual(module.build_result(1,root),'FAILURE')
