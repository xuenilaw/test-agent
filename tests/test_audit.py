"""Offline evidence export and spreadsheet safety, with no live services."""
import contextlib
import csv
import io
import json
import tempfile
import unittest
from pathlib import Path

from test_day6 import fixture_suite
from test_agent.audit import COLUMNS, build_audit, cell
from test_agent.cli import main
from test_agent.reporting import build_report


def read_rows(path):
    with path.open(encoding='utf-8', newline='') as stream:
        return list(csv.DictReader(stream))


class AuditTests(unittest.TestCase):
    def test_all_row_types_statuses_vision_healing_paths_and_formula_safety(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);suite=fixture_suite(root)
            folder=Path(suite['cases'][0]['run_folder'])
            path=folder/'results.json';result=json.loads(path.read_text())
            result['steps'][0]['actions'][0].update(healed=True,reason='=HYPERLINK("bad")\nnext',code='HEALED')
            check=result['steps'][0]['checks'][0]
            check['actual']['answers']['start_city']['probabilities']['Hamburg']=.86
            result['steps'].append(dict(source_step=2,status='NOT_RUN',actions=[dict(action='click',target='@target',status='NOT_RUN')],checks=[]))
            result['steps'][0]['actions'].append(dict(action='click',target='layer',status='PASSED',locator_source='vision',
                provider='anthropic',model='claude-fixture',min_confidence=.9,healed=False))
            result['cleanup'][0]['actual']='';path.write_text(json.dumps(result))
            before=path.read_bytes();output=build_audit(root);rows=read_rows(output)
            self.assertEqual(list(rows[0]),COLUMNS)
            self.assertEqual({r['status'] for r in rows},{'PASSED','FAILED','BLOCKED','NOT_RUN'})
            self.assertEqual(sum(r['row_type']=='case' for r in rows),3)
            self.assertTrue({'case','action','check','cleanup'}<={r['row_type'] for r in rows})
            healed=next(r for r in rows if r['healed']=='Yes')
            self.assertEqual(healed['locator_source'],'healed')
            self.assertEqual(healed['reason_code'],'HEALED')
            self.assertTrue(healed['reason'].startswith("'="))
            self.assertNotIn('\n',healed['reason'])
            visual=next(r for r in rows if r['borderline']=='Yes')
            self.assertEqual(visual['min_confidence'],'0.85')
            self.assertEqual(visual['vision_min_selected_probability'],'0.86')
            self.assertEqual(visual['vision_provider'],'clef')
            self.assertEqual(visual['vision_model'],'cloudflare/clef')
            click=next(r for r in rows if r['locator_source']=='vision' and r['vision_provider']=='anthropic')
            self.assertEqual(click['vision_model'],'claude-fixture')
            self.assertEqual(click['healed'],'No')
            self.assertEqual(visual['screenshot'],'run/CASE-1/screenshot.png')
            self.assertEqual(visual['results_json'],'run/CASE-1/results.json')
            self.assertIn('Hamburg 0.8600',visual['actual'])
            self.assertEqual(path.read_bytes(),before)
            self.assertIn(b'\r\n',output.read_bytes())
            for row in rows:
                for value in row.values():self.assertFalse(value.startswith(('=','+','-','@')))
            self.assertTrue(next(r for r in rows if r['target']=="'@target"))
            self.assertEqual(rows,read_rows(build_audit(root)))
            result['steps'][0]['screenshot']='/etc/passwd'
            path.write_text(json.dumps(result))
            self.assertTrue(all(not r['screenshot'] for r in read_rows(build_audit(root)) if r['case_id']=='CASE-1'))

    def test_repeat_indexes_and_row_ids_are_stable(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);runs=[fixture_suite(root/f'suite-{i}') for i in range(3)]
            repeat=dict(runs=runs,summary=dict(cases=[e for r in runs for e in r['cases']]))
            (root/'repeatability.json').write_text(json.dumps(repeat))
            rows=read_rows(build_audit(root))
            self.assertEqual({r['repeat_index'] for r in rows},{'1','2','3'})
            self.assertEqual(sum(r['row_type']=='case' for r in rows),9)
            self.assertEqual([r['row_id'] for r in rows],[f'R{i:04d}' for i in range(1,len(rows)+1)])
            self.assertEqual(rows,read_rows(build_audit(root)))

    def test_missing_results_still_exports_case_and_rejects_outside_evidence(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);suite=fixture_suite(root)
            suite['cases']=[dict(case_id='NO-RUN',status='BLOCKED',code='TRANSLATION_REJECTED',reason='missing plan',
                translation_folder=str(root/'run/CASE-1'),run_folder=None)]
            (root/'summary.json').write_text(json.dumps(suite))
            row=read_rows(build_audit(root))[0]
            self.assertEqual(row['case_name'],'Fixture CASE-1')
            self.assertEqual(row['status'],'BLOCKED')
            self.assertEqual(row['reason_code'],'TRANSLATION_REJECTED')
            self.assertEqual(row['results_json'],'')

    def test_csv_prefix_and_truncation_and_invalid_cli(self):
        for text in ['=1+1','+1','-2','@SUM(A1)',' \t=1','\r\n+1']:
            self.assertTrue(cell(text).startswith("'"))
        self.assertEqual(cell(True),'Yes')
        self.assertEqual(cell(None),'')
        self.assertEqual(cell('x'*600), 'x'*499+'…')
        with tempfile.TemporaryDirectory() as temp,contextlib.redirect_stdout(io.StringIO()):
            root=Path(temp)
            self.assertEqual(main(['audit',str(root)]),2)
            self.assertFalse((root/'audit.csv').exists())
            fixture_suite(root)
            self.assertEqual(main(['audit',str(root)]),0)
            self.assertTrue((root/'audit.csv').exists())

    def test_html_locator_wording_keeps_raw_csv(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);fixture_suite(root)
            path=root/'run/CASE-1/results.json';result=json.loads(path.read_text())
            result['steps'][0]['actions']=[dict(action='click',target='test',status='PASSED',locator_source=s)
                for s in ['human','cache','healed','vision']]
            path.write_text(json.dumps(result))
            text=build_report(root).read_text()
            for label in ['locator file','cache','healed (GLM)','vision (Claude)','Locator source:']:
                self.assertIn(label,text)
            rows=read_rows(build_audit(root))
            self.assertTrue({'human','cache','healed','vision'}<={r['locator_source'] for r in rows})
