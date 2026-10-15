import contextlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch,AsyncMock
from test_executor import ROOT
from test_agent.readers.excel import read_case,read_case_ids
from test_agent.schemas.contracts import parse_contract
from test_agent.schemas.plan import TranslationPlan,Assertion
from test_agent.suite import run_suite,reusable_plan
from test_agent.runner import run_case
from test_agent.translation.validator import validate_plan
from test_agent.verification.vision import endpoint_matches,decide,VisualObservation
from test_agent.verification.checks import verify
from test_vision import FakeVision


def layer_folder(root):
    case=read_case(ROOT/'cases/osm/WBS_testcase1_osm.xlsx','OSM-003')
    contract=parse_contract(json.loads((ROOT/'cases/osm/contracts.json').read_text())['OSM-003']).model_dump()
    actions=[[dict(action='navigate',target='OSM Website',value='https://www.openstreetmap.org/')],
             [dict(action='click',target='layers control')],
             [dict(action='select',target='map layer selector',value=contract['selected_layer'])]]
    checks=[[dict(kind='visible',target='OSM Website')],
            [dict(kind='options_present',target='map layers panel',value=contract['expected_options'],operator='equals')],
            [dict(kind='selected',target='map layer selector',value=contract['selected_layer'],operator='equals')]]
    plan=TranslationPlan(case_id=case['case_id'],preconditions=case['preconditions'],issues=[],notes=[],
        steps=[dict(source_step=i+1,source_action=case['actions'][i]['text'],source_expected=case['expected'][i]['text'],actions=actions[i],checks=checks[i]) for i in range(3)],
        cleanup=[dict(action='select',target='map layer selector',value='Standard'),dict(action='click',target='layers panel close button')])
    folder=root/'translation-layers/cases/OSM-003';folder.mkdir(parents=True)
    path=root/'contracts.json';path.write_text(json.dumps({'OSM-003':contract}))
    source=dict(case=case,contract=contract,contract_file=str(path),application_url='https://www.openstreetmap.org/')
    for name,data in [('source',source),('plan',plan.model_dump()),('validation',dict(status='VALIDATED',errors=[]))]:
        (folder/f'{name}.json').write_text(json.dumps(data))
    return folder,plan,case,contract


class SuiteTests(unittest.IsolatedAsyncioTestCase):
    async def test_three_cases_rejected_middle_continues_and_designed_status_stays_real(self):
        with tempfile.TemporaryDirectory() as temp:
            async def translate(args,report_sink,quiet):
                report_sink.update(status='REJECTED' if args.case=='OSM-002' else 'VALIDATED',errors=['bad plan'] if args.case=='OSM-002' else [],output_directory=str(Path(temp)/args.case))
            called=[]
            async def execute(folder,*args,**kwargs):
                called.append(folder.name)
                return SimpleNamespace(status='PASSED',reason=None,output_directory=str(folder/'run'))
            with patch('test_agent.cli.run_translation',side_effect=translate),patch('test_agent.suite.run_case',side_effect=execute),contextlib.redirect_stdout(io.StringIO()):
                summary=await run_suite(ROOT/'cases/osm/WBS_testcase1_osm.xlsx',Path('unused'),ROOT,output_root=Path(temp))
            self.assertEqual(called,['OSM-001','OSM-003'])
            self.assertEqual([e['status'] for e in summary['cases']],['PASSED','BLOCKED','PASSED'])
            self.assertEqual(summary['cases'][1]['code'],'TRANSLATION_REJECTED')
            self.assertFalse(summary['cases'][1]['outcome_as_designed'])
            self.assertTrue(summary['cases'][2]['outcome_as_designed'])

    def test_case_ids_order_and_reuse_hit_miss(self):
        book=ROOT/'cases/osm/WBS_testcase1_osm.xlsx'
        self.assertEqual(read_case_ids(book),['OSM-001','OSM-002','OSM-003'])
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);folder=root/'translation-test/cases/OSM-001';folder.mkdir(parents=True)
            (folder/'validation.json').write_text('{}')
            source=dict(case={'source':{'file':str(book)}},application_url='https://www.openstreetmap.org/',
                        vocabulary={'targets':{'x':'description'}})
            with patch('test_agent.suite.load_plan',return_value=(None,source)):
                self.assertEqual(reusable_plan(root,book,'OSM-001','https://www.openstreetmap.org/'),folder)
            with patch('test_agent.suite.load_plan',side_effect=ValueError('stale')):
                self.assertIsNone(reusable_plan(root,book,'OSM-001','https://www.openstreetmap.org/'))

    def test_layer_contract_positive_and_negative(self):
        with tempfile.TemporaryDirectory() as temp:
            _,plan,case,contract=layer_folder(Path(temp))
            self.assertEqual(validate_plan(plan,case,'https://www.openstreetmap.org/',contract),[])
            plan.steps[1].checks[0].value=['Standard']
            self.assertTrue(validate_plan(plan,case,'https://www.openstreetmap.org/',contract))
            plan.steps[1].checks[0].value=contract['expected_options']
            plan.cleanup.reverse()
            self.assertTrue(validate_plan(plan,case,'https://www.openstreetmap.org/',contract))
            with self.assertRaises(ValueError):
                parse_contract({**contract,'type':'unknown'})
            with self.assertRaises(ValueError):
                Assertion(kind='visible',target='x',value=['x'])

    def test_city_alias_is_exact_and_used_by_vision(self):
        self.assertTrue(endpoint_matches('München, Germany','Munich',['München']))
        self.assertFalse(endpoint_matches('Münchenberg','Munich',['München']))
        observation=VisualObservation.model_validate({**FakeVision().observation,'end_marker_city':'München'})
        req={'origin':'Hamburg','destination':'Munich'}
        self.assertEqual(decide(observation,req,.9)[0],'FAILED')
        self.assertEqual(decide(observation,{**req,'destination_aliases':['München']},.9)[0],'PASSED')

    def test_plan_route_check_accepts_only_declared_city_alias(self):
        from test_executor import translation_folder
        with tempfile.TemporaryDirectory() as temp:
            folder = translation_folder(Path(temp))
            plan = TranslationPlan.model_validate_json((folder/'plan.json').read_text())
            source = json.loads((folder/'source.json').read_text())
            contract = source['contract']
            contract['destination_aliases'] = ['Capital']
            route = next(c for c in plan.steps[3].checks if c.kind == 'route_connects')
            route.value = 'Hamburg - Capital'
            self.assertFalse(validate_plan(plan,source['case'],source['application_url'],contract))
            route.value = 'Hamburg - Berlinberg'
            self.assertIn('Route check must preserve both cities.',validate_plan(plan,source['case'],source['application_url'],contract))

    async def test_dom_route_uses_city_alias(self):
        for aliases,status in [([], 'FAILED'),(['München'],'PASSED')]:
            resolver=SimpleNamespace(resolve=AsyncMock(side_effect=[
                (SimpleNamespace(inner_text=AsyncMock(return_value='Route')),None),
                (SimpleNamespace(input_value=AsyncMock(return_value='Hamburg, Germany')),None),
                (SimpleNamespace(input_value=AsyncMock(return_value='München, Germany')),None)]))
            checked=await verify(None,resolver,Assertion(kind='route_connects',target='route',value='Hamburg to Munich',operator='equals'),
                dict(origin='Hamburg',destination='Munich',destination_aliases=aliases))
            self.assertEqual(checked.status,status)

    async def test_designed_failure_remains_failed_and_reuse_skips_translation(self):
        with tempfile.TemporaryDirectory() as temp:
            translated=[]
            async def translate(args,report_sink,quiet):
                translated.append(args.case)
                report_sink.update(status='VALIDATED',errors=[],output_directory=str(Path(temp)/args.case))
            async def execute(folder,*args,**kwargs):
                return SimpleNamespace(status='FAILED' if folder.name=='OSM-002' else 'PASSED',reason='duration failure' if folder.name=='OSM-002' else None,output_directory=str(folder/'run'))
            with patch('test_agent.cli.run_translation',side_effect=translate),patch('test_agent.suite.run_case',side_effect=execute),patch(
                    'test_agent.suite.reusable_plan',side_effect=[Path(temp)/'OSM-001',None,None]),contextlib.redirect_stdout(io.StringIO()):
                summary=await run_suite(ROOT/'cases/osm/WBS_testcase1_osm.xlsx',Path('unused'),ROOT,output_root=Path(temp),reuse=True)
            self.assertEqual(translated,['OSM-002','OSM-003'])
            self.assertTrue(summary['cases'][0]['reused'])
            self.assertEqual(summary['status'],'FAILED')
            self.assertTrue(all(e['outcome_as_designed'] for e in summary['cases']))


@unittest.skipUnless(any(p.is_file() for p in (ROOT/'.browsers').rglob('chrome-headless-shell')),'Project Chromium missing')
class LayerBrowserTests(unittest.IsolatedAsyncioTestCase):
    async def test_layer_selected_cleanup_and_options_missing_extra(self):
        os.environ.setdefault('PLAYWRIGHT_BROWSERS_PATH',str(ROOT/'.browsers'))
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);folder,_,_,_=layer_folder(root)
            for missing in [False,True]:
                async def intercept(route):
                    html=(ROOT/'tests/fixtures/fake_layers.html').read_text()
                    html=html.replace('</div></div></div>','<input type="radio" id="extra"><label for="extra">Extra Layer</label></div></div></div>')
                    if missing: html=html.replace('>CyclOSM<','>Wrong<')
                    await route.fulfill(status=200,content_type='text/html',body=html)
                result=await run_case(folder,ROOT/'cases/osm/locators.json',ROOT,output_root=root,route_handler=intercept,timeout=600)
                self.assertEqual(result.status,'FAILED' if missing else 'PASSED',result.model_dump())
                check=result.steps[1].checks[0]
                self.assertIn('Extra Layer',check.actual['extra'])
                self.assertEqual(check.actual['missing'],['CyclOSM'] if missing else [])
                if not missing:
                    self.assertEqual(result.steps[2].checks[0].actual['value'],'Tracestrack Topo')
                    self.assertTrue(all(c['status']=='PASSED' for c in result.cleanup))
