"""Offline JUnit semantics, portable downloads, and protected artifact pruning."""
import contextlib
import io
import json
import os
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest.mock import AsyncMock, patch
from zipfile import ZipFile

from browser_support import chromium_available
from test_day6 import fixture_suite
from test_executor import ROOT
from test_suite import layer_folder
from test_agent.artifacts import DOWNLOADS, package_reports, prune
from test_agent.cli import main
from test_agent.junit import build_junit
from test_agent.plan_loader import load_plan
from test_agent.runner import run_case
from test_agent.suite import reusable_plan, run_suite


class JUnitTests(unittest.TestCase):
    def test_status_mapping_counts_escaping_and_diagnostic_lines(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            summary = fixture_suite(root)
            folder = Path(summary['cases'][0]['run_folder'])
            result = json.loads((folder/'results.json').read_text())
            original = result['steps'][0]
            result['steps'] = [{**original, 'source_step': n, 'status': status, 'reason': '<bad>&\x00\ud800'}
                               for n, status in enumerate(['PASSED', 'FAILED', 'BLOCKED', 'NOT_RUN'], 1)]
            result['steps'][0]['checks'][0]['actual']['answers']['start_city']['probabilities']['Hamburg'] = .86
            (folder/'results.json').write_text(json.dumps(result))
            plan = {'steps': [{'source_step': n, 'source_action': '<script>evil</script> & "\x01\ufffe',
                               'source_expected': 'route'} for n in range(1, 5)]}
            (folder/'plan.json').write_text(json.dumps(plan))
            path = build_junit(root)
            xml = ET.parse(path).getroot()
            suite = xml.find('testsuite')
            self.assertEqual({k: suite.get(k) for k in ['tests','failures','errors','skipped','time']},
                             dict(tests='5',failures='1',errors='1',skipped='1',time='1'))
            nodes = suite.findall('testcase')
            self.assertIsNone(nodes[0].find('failure'))
            self.assertIsNotNone(nodes[1].find('failure'))
            self.assertIsNotNone(nodes[2].find('error'))
            self.assertIsNotNone(nodes[3].find('skipped'))
            self.assertEqual(nodes[4].get('name'), 'Cleanup')
            self.assertIn('<script>evil</script>', nodes[0].get('name'))
            text = nodes[0].findtext('system-out')
            for expected in ['(borderline)', 'Hamburg 0.8600', 'locator_source: healed',
                             'reason_code:', 'screenshot: run/CASE-1/screenshot.png',
                             'results.json: run/CASE-1/results.json']:
                self.assertIn(expected, text)
            self.assertNotIn(str(root), text)
            self.assertEqual(suite.find("properties/property[@name='outcome_as_designed']").get('value'), 'Yes')
            self.assertNotIn('\x00', path.read_text())
            self.assertEqual(len(xml.findall('testsuite')), 3)
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(main(['junit', str(root)]), 0)
                self.assertEqual(main(['junit', str(root/'missing')]), 2)

    def test_translation_rejected_missing_evidence_and_repeat_aggregate(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            summary = fixture_suite(root)
            summary['cases'] = [dict(case_id='REJECTED',status='BLOCKED',code='TRANSLATION_REJECTED',
                                     reason='unknown target',duration_seconds=2),
                                dict(case_id='MISSING',status='BLOCKED')]
            (root/'summary.json').write_text(json.dumps(summary))
            suites = ET.parse(build_junit(root)).getroot().findall('testsuite')
            self.assertEqual(suites[0].find('testcase').get('name'), 'Translation')
            self.assertEqual(suites[0].get('errors'), '1')
            self.assertEqual(suites[1].find('testcase').get('name'), 'Execution')
            (root/'repeatability.json').write_text(json.dumps(dict(summary=summary, runs=[summary, summary])))
            suites = ET.parse(build_junit(root)).getroot().findall('testsuite')
            self.assertEqual(len(suites), 4)
            self.assertNotEqual(suites[0].find('testcase').get('name'), suites[2].find('testcase').get('name'))

    def test_package_links_work_after_extracting_evidence_and_old_paths_rebase(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            suite = root/'suite-original'
            summary = fixture_suite(suite)
            # Simulate a saved Jenkins archive with paths from another machine.
            for path in list(suite.rglob('*.json')):
                path.write_text(path.read_text().replace(str(suite), '/old/jenkins/artifacts/suite-original'))
            reports = package_reports(suite, root/'reports')
            self.assertEqual({p.name for p in reports.iterdir()}, set(DOWNLOADS))
            text = (reports/'report.html').read_text()
            self.assertIn('href="run/CASE-1/screenshot.png"', text)
            self.assertIn('data:image/jpeg;base64,', text)
            with ZipFile(reports/'evidence.zip') as archive:
                self.assertNotIn('report.html', archive.namelist())
                self.assertIn('run/CASE-1/trace.zip', archive.namelist())
                archive.extractall(reports)
            self.assertTrue((reports/'run/CASE-1/screenshot.png').is_file())
            self.assertTrue((reports/'run/CASE-1/results.json').is_file())
            with self.assertRaises(ValueError):
                package_reports(suite, suite/'reports')
            with self.assertRaises(ValueError):
                package_reports(suite, reports)  # Don't overwrite an extracted evidence tree.

    def test_prune_defaults_to_preview_and_keeps_protected_paths(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)/'artifacts'; root.mkdir()
            for n, name in enumerate(['suite-old','repeat-old','run-new','translation-new']):
                folder = root/name; folder.mkdir(); (folder/'data').write_text('keep evidence')
                os.utime(folder, ns=(n+1, n+1))
            protected = [root/'calibration-frozen', root/'cases', Path(temp)/'cases']
            for folder in protected:
                folder.mkdir(); (folder/'keep').write_text('protected')
            cache = root/'locators.cache.json'; cache.write_text('{}')
            (root/'suite-link').symlink_to(protected[-1], target_is_directory=True)
            victims = prune(root, keep=2)
            self.assertEqual({p.name for p in victims}, {'suite-old','repeat-old'})
            self.assertTrue(all(p.exists() for p in victims))
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(main(['--project-dir', temp, 'prune', '--keep', '2']), 0)
                self.assertEqual(main(['--project-dir', temp, 'prune', '--keep', '-1']), 2)
                self.assertEqual(main(['--project-dir', temp, 'prune', '--keep', '2', '--yes']), 0)
            self.assertTrue(all(not p.exists() for p in victims))
            self.assertTrue(all((p/'keep').is_file() for p in protected))
            self.assertTrue(cache.exists())
            self.assertTrue((root/'suite-link').is_symlink())
            with self.assertRaises(ValueError):
                prune(Path(temp)/'cases', keep=0, yes=True)


@unittest.skipUnless(chromium_available(), 'Project Chromium missing')
class LayoutTests(unittest.IsolatedAsyncioTestCase):
    async def test_fake_translation_browser_layout_reuse_and_revalidation(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            _, plan, _, _ = layer_folder(root/'fixture')
            async def execute(folder, locators, project, **kwargs):
                async def route(request):
                    await request.fulfill(status=200, content_type='text/html',
                                          body=(ROOT/'tests/fixtures/fake_layers.html').read_text())
                return await run_case(folder, locators, project, route_handler=route, **kwargs)
            artifacts = root/'artifacts'
            with patch('test_agent.suite.read_case_ids',return_value=['OSM-003']), patch.dict(os.environ,
                    {'OPENAI_API_KEY':'fake','OPENAI_MODEL':'offline'}), patch('test_agent.cli.translate',
                    new=AsyncMock(return_value=plan.model_dump_json())) as model, patch(
                    'test_agent.suite.run_case',side_effect=execute), contextlib.redirect_stdout(io.StringIO()):
                summary = await run_suite(ROOT/'cases/osm/WBS_testcase1_osm.xlsx',
                    ROOT/'cases/osm/locators.json', ROOT, output_root=artifacts)
                output = Path(summary['output_directory'])
                self.assertEqual(summary['status'], 'PASSED', summary)
                self.assertEqual(Path(summary['cases'][0]['translation_folder']), output/'cases/OSM-003/translation')
                self.assertTrue((output/'cases/OSM-003/run/results.json').exists())
                self.assertEqual({p.name for p in output.iterdir()}, {'cases','summary.json','report.html','audit.csv','junit.xml'})
                model.assert_awaited_once()
                reused = await run_suite(ROOT/'cases/osm/WBS_testcase1_osm.xlsx', ROOT/'cases/osm/locators.json',
                                         ROOT, output_root=artifacts, reuse=True)
                self.assertEqual(reused['status'], 'PASSED', reused)
                self.assertTrue(reused['cases'][0]['reused'])
                model.assert_awaited_once()
                folder = reusable_plan(artifacts, ROOT/'cases/osm/WBS_testcase1_osm.xlsx', 'OSM-003',
                                       'https://www.openstreetmap.org/')
                load_plan(folder)
                self.assertEqual(main(['--project-dir', str(root), 'revalidate', str(folder)]), 0)
                self.assertTrue(list(artifacts.glob('translation-*/cases/OSM-003/plan.json')))
