"""Threshold policy, safe offline HTML, and execution-only repeatability."""
import contextlib
import copy
import io
import json
import os
import tempfile
import unittest
from html.parser import HTMLParser
from types import SimpleNamespace
from pathlib import Path
from unittest.mock import AsyncMock,patch

from PIL import Image
from test_executor import ROOT
from test_agent.cli import main
from test_agent.schemas.contracts import VisionCheck,threshold_for
from test_agent.verification.vision_providers import click_provider_from_env,VisionError
from test_agent.verification.calibration import rescore
from test_agent.reporting import build_report,CALIBRATION_CAVEAT,borderline,readable_item
from test_agent.repeatability import summarize_repeats,run_repeat
from test_agent.runner import run_case

MALICIOUS='<script>alert(1)</script>'


class DetailSummaries(HTMLParser):
    def __init__(self,text):
        super().__init__();self.nodes=[];self.stack=[];self.in_summary=False
        self.feed(text)

    def handle_starttag(self,tag,attrs):
        if tag=='details':
            node=dict(attrs=dict(attrs),summary='')
            self.nodes.append(node);self.stack.append(node)
        elif tag=='summary':self.in_summary=True

    def handle_endtag(self,tag):
        if tag=='summary':self.in_summary=False
        elif tag=='details':self.stack.pop()

    def handle_data(self,data):
        if self.in_summary and self.stack:self.stack[-1]['summary']+=data


def fixture_suite(root):
    root.mkdir(parents=True,exist_ok=True)
    entries=[]
    for i,status in enumerate(['PASSED','FAILED','BLOCKED']):
        case=f'CASE-{i+1}';folder=root/'run'/case;folder.mkdir(parents=True,exist_ok=True)
        image=folder/'screenshot.png';Image.new('RGB',(1280,800),'white').save(image)
        check=dict(kind='route_geometry',target='vision map',status=status,reason=MALICIOUS,
            actual=dict(provider='clef',model='cloudflare/clef',min_confidence=.85,api_host='openrouter.ai',
                upstream_provider='Fixture upstream',model_summary=MALICIOUS,answers={
                    'start_city':dict(choice='Hamburg',probabilities={'Hamburg':.9,'unclear':.1},confidence=.8)}))
        result=dict(case_id=case,status=status,reason=MALICIOUS,steps=[dict(source_step=1,status=status,reason=MALICIOUS,
            actions=[dict(action='click',target=MALICIOUS,status='PASSED',locator_source='healed' if i==0 else 'vision',
                provider='anthropic',model='claude-test',min_confidence=.90)],checks=[check],screenshot=str(image))],
            cleanup=[dict(action='click',status='PASSED',target='Close')])
        plan=dict(preconditions='Internet available',steps=[dict(source_step=1,source_action=MALICIOUS,source_expected='Expected result')])
        for name,value in [('results',result),('plan',plan),('source',dict(case=dict(name='Fixture '+case)))]:
            (folder/(name+'.json')).write_text(json.dumps(value))
        (folder/'trace.zip').write_bytes(b'fixture')
        entries.append(dict(case_id=case,status=status,reason=MALICIOUS,run_folder=str(folder),duration_seconds=1+i,
            execution_seconds=1+i,designed_outcome=status,outcome_as_designed=True,heals=1 if i==0 else 0,
            vision_click_attempts=int(i==1),vision_click_successes=int(i==1)))
    suite=dict(cases=entries,status='FAILED',reason=None,workbook=MALICIOUS,started_at='2026-10-15T12:00:00Z',
        totals=dict(PASSED=1,FAILED=1,BLOCKED=1),tool=dict(version='0.1.0',git_commit='fixture'),
        faults_injected=['fixture'],output_directory=str(root))
    (root/'summary.json').write_text(json.dumps(suite))
    return suite


class Day6Tests(unittest.IsolatedAsyncioTestCase):
    def test_steps_and_cleanup_are_collapsed_with_safe_short_summaries(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);fixture_suite(root)
            folder=root/'run/CASE-1'
            plan=json.loads((folder/'plan.json').read_text())
            action=MALICIOUS+'\n '+('long action '*20)
            plan['steps']=[dict(source_step=i,source_action=action,source_expected='Expected') for i in range(1,5)]
            (folder/'plan.json').write_text(json.dumps(plan))
            result=json.loads((folder/'results.json').read_text())
            reason='Reason '+MALICIOUS+'\n '+('long reason '*20)
            result['steps']=[dict(source_step=i,status=status,reason=reason,actions=[],checks=[],screenshot=None)
                for i,status in enumerate(['PASSED','FAILED','BLOCKED','NOT_RUN'],1)]
            result['cleanup']=[dict(action='click',target='Close',status='FAILED')]
            (folder/'results.json').write_text(json.dumps(result))
            before=(folder/'results.json').read_bytes()
            text=build_report(root).read_text()
            nodes=DetailSummaries(text).nodes
            steps=[n for n in nodes if n['attrs'].get('class')=='step'][:4]
            self.assertEqual(len(steps),4)
            short_action=' '.join(action.split())[:99]+'…'
            short_reason=' '.join(reason.split())[:119]+'…'
            for i,(node,status) in enumerate(zip(steps,['PASSED','FAILED','BLOCKED','NOT_RUN']),1):
                self.assertNotIn('open',node['attrs'])
                expected=f'Step {i} – {short_action} {status}'
                if status!='PASSED':expected+=' · '+short_reason
                self.assertEqual(node['summary'],expected)
                self.assertNotIn('\n',node['summary'])
            cleanup=next(n for n in nodes if n['attrs'].get('class')=='cleanup')
            self.assertNotIn('open',cleanup['attrs'])
            self.assertEqual(cleanup['summary'],'Cleanup – 1 actions FAILED')
            self.assertNotIn('<script>',text)
            self.assertIn('&lt;script&gt;',text)
            self.assertEqual((folder/'results.json').read_bytes(),before)

    def test_collapsed_step_keeps_borderline_badge_and_cleanup_empty_is_not_run(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);fixture_suite(root)
            path=root/'run/CASE-1/results.json';result=json.loads(path.read_text())
            result['steps'][0]['checks'][0]['actual']['answers']['start_city']['probabilities']['Hamburg']=.86
            result['cleanup']=[];path.write_text(json.dumps(result))
            text=build_report(root).read_text();nodes=DetailSummaries(text).nodes
            step=next(n for n in nodes if n['attrs'].get('class')=='step')
            self.assertTrue(step['summary'].endswith('PASSED (borderline)'))
            cleanup=next(n for n in nodes if n['attrs'].get('class')=='cleanup')
            self.assertEqual(cleanup['summary'],'Cleanup – 0 actions NOT_RUN')
            self.assertIn('Technical details',text)
            self.assertIn('Vision evidence',text)
            self.assertIn('data:image/jpeg;base64,',text)

    def test_readability_summary_page_type_and_human_formatting(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);runs=[fixture_suite(root/f'suite-{i}') for i in range(3)]
            for run in runs:
                run['faults_injected']=[];run['tool']['working_tree_dirty']=True
                folder=Path(run['cases'][1]['run_folder'])
                source=json.loads((folder/'source.json').read_text())
                source['contract']=dict(origin='Hamburg',destination='Munich')
                (folder/'source.json').write_text(json.dumps(source))
                result=json.loads((folder/'results.json').read_text())
                result['steps'][0]['checks'][0]['status']='BLOCKED'
                result['steps'].append(dict(source_step=5,status='FAILED',actions=[],checks=[dict(kind='duration_minutes',
                    status='FAILED',expected=dict(operator='less_than',value=180),actual=dict(raw_text='7:36',parsed_minutes=456))]))
                (folder/'results.json').write_text(json.dumps(result))
                (Path(run['output_directory'])/'summary.json').write_text(json.dumps(run))
            entries=[dict(e,run_label=f'Run {i+1}') for i,r in enumerate(runs) for e in r['cases']]
            repeat=dict(runs=runs,cases=summarize_repeats(runs),summary=dict(runs[0],cases=entries))
            (root/'repeatability.json').write_text(json.dumps(repeat))
            text=build_report(root).read_text()
            for expected in ['Same 3 cases run 3 times','3 suite runs × 3 cases','Run 1 report',
                    'CASE-2 (Hamburg → Munich): FAILED as designed.',
                    'Step 5 duration 7 h 36 min is not under 3 h.',
                    'Route picture: Clef unsure (UNCLEAR).','Faults: none','Yes','1.0 s','Technical details']:
                self.assertIn(expected,text)
            for unwanted in ['Faults: []','True','False','0 / 0 successful of 0 attempts','{&#x27;','[&#x27;']:
                self.assertNotIn(unwanted,text)
            self.assertIn('<td>—</td>',text)
            self.assertIn('This suite report contains one run of 3 cases.',build_report(root/'suite-0').read_text())

    def test_borderline_pass_is_display_only_and_readable_numbers_remain(self):
        check=dict(kind='route_geometry',status='PASSED',expected=dict(description='Continuous route from Hamburg to Berlin'),actual=dict(min_confidence=.85,
            answers={'end_city':dict(choice='Berlin',probabilities={'Berlin':.856})}))
        original=copy.deepcopy(check)
        self.assertTrue(borderline(check))
        self.assertIn('Berlin 0.8560',readable_item(check))
        self.assertIn('Expected: Continuous route from Hamburg to Berlin',readable_item(check))
        self.assertEqual(check,original)
        for value,status,expected in [(.88,'PASSED',True),(.881,'PASSED',False),(.849,'PASSED',False),(.856,'BLOCKED',False)]:
            changed=copy.deepcopy(check);changed['status']=status
            changed['actual']['answers']['end_city']['probabilities']['Berlin']=value
            self.assertEqual(borderline(changed),expected)
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);fixture_suite(root)
            path=root/'run/CASE-1/results.json';data=json.loads(path.read_text())
            data['steps'][0]['checks']=[check];path.write_text(json.dumps(data))
            text=build_report(root).read_text()
            self.assertIn('PASSED (borderline)',text)
            self.assertIn('Berlin 0.8560',text)
            self.assertEqual(json.loads(path.read_text()),data)
    async def test_missing_provider_entry_rejects_before_browser(self):
        source=dict(contract=dict(vision_checks=[dict(step=4,kind='route_geometry',requirement='route',
            min_confidence={'clef':.85,'anthropic':.90})]))
        with patch('test_agent.runner.load_plan',return_value=(SimpleNamespace(steps=[]),source)),patch(
                'test_agent.runner.async_playwright') as browser,self.assertRaisesRegex(ValueError,'provider glm'):
            await run_case(Path('unused'),Path('unused'),ROOT,vision_provider=SimpleNamespace(provider_name='glm'))
        browser.assert_not_called()

    def test_per_provider_thresholds_validate_without_hidden_default(self):
        definition=dict(step=4,kind='route_geometry',requirement='route',min_confidence={'clef':.85,'anthropic':.9})
        typed=VisionCheck.model_validate(definition).model_dump()
        self.assertEqual(threshold_for(typed,'clef'),.85)
        self.assertEqual(threshold_for(typed,'anthropic'),.9)
        with self.assertRaisesRegex(ValueError,'no min_confidence'):
            threshold_for(typed,'glm')
        self.assertEqual(threshold_for({**definition,'min_confidence':.88},'legacy'),.88)
        for value in [{},{'clef':.5},{'clef':1.1},{'clef':float('nan')},{'clef':True}]:
            with self.assertRaises(ValueError):
                VisionCheck.model_validate({**definition,'min_confidence':value})

    def test_saved_clef_replay_point85_zero_false_and_missed_pass_both_sets(self):
        data=json.loads((ROOT/'tests/fixtures/clef_threshold_replay.json').read_text())
        for name,group in data['sets'].items():
            records=[r for r in group['images'] for _ in range(r['repetitions'])]
            result=rescore(records,.85)
            self.assertEqual((result['false_pass'],result['missed_pass']),(0,0),name)
            self.assertEqual(result['calls'],40 if name=='original' else 25)

    def test_clef_route_configuration_uses_separate_claude_for_clicks(self):
        with patch.dict(os.environ,dict(VISION_PROVIDER='clef',VISION_MODEL='cloudflare/clef',
                OPENROUTER_API_KEY='router-key',ANTHROPIC_API_KEY='anthropic-key',VISION_CLICK_MODEL='claude-click'),clear=True):
            click=click_provider_from_env()
            self.assertEqual(click.provider_name,'anthropic')
            self.assertEqual(click.api_key,'anthropic-key')
            self.assertEqual(click.model,'claude-click')
        with patch.dict(os.environ,dict(VISION_PROVIDER='clef',OPENROUTER_API_KEY='not-anthropic'),clear=True),self.assertRaises(VisionError):
            click_provider_from_env()

    def test_report_escapes_all_untrusted_text_and_embeds_offline_thumbnails(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);fixture_suite(root)
            path=build_report(root);text=path.read_text()
            self.assertNotIn(MALICIOUS,text)
            self.assertIn('&lt;script&gt;alert(1)&lt;/script&gt;',text)
            self.assertIn('data:image/jpeg;base64,',text)
            self.assertNotRegex(text,r'(?:src|href)=["\'](?:https?:|//|javascript:)')
            self.assertNotIn('<script',text)
            for value in ['PASSED','FAILED','BLOCKED','healed','vision','probabilities','Fixture upstream','0.85','0.9','results.json','trace.zip','post-hoc']:
                self.assertIn(value,text)
            self.assertIn('Full-size screenshot',text)

    def test_missing_screenshot_or_outside_asset_does_not_break_or_link_report(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);fixture_suite(root)
            for image in root.rglob('screenshot.png'):image.unlink()
            path=build_report(root)
            self.assertIn('Screenshot unavailable',path.read_text())
            result=root/'run/CASE-1/results.json';data=json.loads(result.read_text())
            data['steps'][0]['screenshot']='/etc/passwd';result.write_text(json.dumps(data))
            self.assertNotIn('/etc/passwd',build_report(root).read_text())
        with tempfile.TemporaryDirectory() as temp,self.assertRaises(ValueError):
            build_report(Path(temp))

    def test_repeat_analysis_reports_status_and_step_differences_and_probability_spread(self):
        with tempfile.TemporaryDirectory() as temp:
            runs=[fixture_suite(Path(temp)/f'suite-{i}') for i in range(3)]
            runs[1]['cases'][0]['status']='BLOCKED'
            path=Path(runs[1]['cases'][0]['run_folder'])/'results.json'
            result=json.loads(path.read_text());result['steps'][0].update(status='BLOCKED',reason='Vision uncertain')
            actual=result['steps'][0]['checks'][0]['actual']
            actual['answers']['start_city']['probabilities']={'Hamburg':.8,'unclear':.2}
            actual['upstream_provider']='Other upstream'
            path.write_text(json.dumps(result))
            cases=summarize_repeats(runs);first=cases[0]
            self.assertEqual(first['statuses'],['PASSED','BLOCKED','PASSED'])
            self.assertFalse(first['consistent'])
            self.assertEqual(first['differences'][0]['step'],1)
            check=first['vision_checks'][0]
            self.assertEqual(check['probability_spread']['start_city']['options']['Hamburg'],dict(min=.8,max=.9))
            self.assertEqual(check['upstream_providers_seen'],['Fixture upstream','Other upstream'])
            self.assertEqual(first['durations']['mean'],1)

    async def test_repeat_never_translates_and_writes_html_json(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            async def suite(*args,**kwargs):
                self.assertTrue(kwargs['require_reuse'])
                return fixture_suite(kwargs['output_folder'])
            with patch('test_agent.repeatability.read_case_ids',return_value=['CASE-1']),patch(
                    'test_agent.repeatability.reusable_plan',return_value=root/'validated'),patch(
                    'test_agent.repeatability.load_plan'),patch('test_agent.repeatability.run_suite',side_effect=suite),patch(
                    'test_agent.cli.translate') as translator,contextlib.redirect_stdout(io.StringIO()):
                report=await run_repeat(Path('book'),Path('locators'),ROOT,times=3,output_root=root)
            translator.assert_not_called()
            output=Path(report['output_directory'])
            self.assertTrue((output/'repeatability.json').exists())
            self.assertTrue((output/'junit.xml').exists())
            self.assertEqual([Path(run['output_directory']).name for run in report['runs']], ['run-1','run-2','run-3'])
            self.assertIn('Repeatability',(output/'report.html').read_text())
            self.assertTrue(all(c['consistent'] for c in report['cases']))
            with patch('test_agent.repeatability.read_case_ids',return_value=['CASE-1']),patch(
                    'test_agent.repeatability.reusable_plan',return_value=None),patch('test_agent.repeatability.run_suite') as run:
                with self.assertRaises(ValueError):
                    await run_repeat(Path('book'),Path('locators'),ROOT,times=3,output_root=root)
                run.assert_not_called()
            for times in [0,True,101]:
                with self.assertRaises(ValueError):
                    await run_repeat(Path('book'),Path('locators'),ROOT,times=times,output_root=root)
