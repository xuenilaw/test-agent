"""Offline fault injection and guarded vision-click evidence."""
import contextlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from test_executor import ROOT, translation_folder
from test_healing import FakePlanner
from test_suite import layer_folder
from test_vision import FakeVision, declare_vision, http_reply
from test_agent.cli import main
from test_agent.faults import validate_fault_targets, intercept_fault
from test_agent.plan_loader import load_plan
from test_agent.runner import run_case
from test_agent.suite import run_suite
from test_agent.verification.vision_providers import ClaudeVision
from test_agent.schemas.plan import AtomicAction
from test_agent.tools.dom import Blocked, perform


class FakeClick:
    def __init__(self, **changes):
        self.data = dict(found=True,x=120.0,y=120.0,confidence=.95,summary='Layers control at this point.')
        self.data.update(changes)
        self.calls = []

    async def locate_click(self,image,description):
        self.calls.append((image,description))
        return dict(provider='fake',model='offline',content=json.dumps(self.data))


class FaultInputTests(unittest.IsolatedAsyncioTestCase):
    async def test_suite_preflights_faults_and_only_injects_matching_cases(self):
        with tempfile.TemporaryDirectory() as temp:
            async def translate(args,report_sink,quiet):
                report_sink.update(status='VALIDATED',errors=[],output_directory=str(Path(temp)/args.case))
            def loaded(folder):
                target='layers control' if folder.name=='OSM-003' else 'starting-point field'
                action=SimpleNamespace(action='click' if target=='layers control' else 'fill',target=target)
                return SimpleNamespace(steps=[SimpleNamespace(actions=[action])]),dict(vocabulary=dict(targets={
                    'layers control':'Opens layers','starting-point field':'Origin','map layers panel':'Options'}))
            async def execute(folder,*args,**kwargs):
                return SimpleNamespace(status='PASSED',reason=None,output_directory='fake',outcome_as_designed=True,
                    vision_click_attempts=1 if kwargs['faults'] else 0,vision_click_successes=1 if kwargs['faults'] else 0)
            with patch('test_agent.cli.run_translation',side_effect=translate),patch('test_agent.suite.load_plan',side_effect=loaded),patch(
                    'test_agent.suite.run_case',side_effect=execute) as run,contextlib.redirect_stdout(io.StringIO()):
                summary=await run_suite(ROOT/'cases/osm/WBS_testcase1_osm.xlsx',Path('unused'),ROOT,output_root=Path(temp),faults=['vision-click:layers control'])
                self.assertEqual([c.kwargs['faults'] for c in run.call_args_list],[[],[],['vision-click:layers control']])
                self.assertEqual(summary['totals']['vision_click_attempts'],1)
                run.reset_mock()
                with self.assertRaises(ValueError):
                    await run_suite(ROOT/'cases/osm/WBS_testcase1_osm.xlsx',Path('unused'),ROOT,output_root=Path(temp),faults=['broken-locator:map layers panel'])
                run.assert_not_called()

    async def test_nonclick_actions_never_invoke_vision_fallback(self):
        for kind in ['fill','select','press']:
            resolver=SimpleNamespace(resolve_action=AsyncMock(side_effect=Blocked('missing',code='NO_LOCATOR')),
                                     click_fallback=AsyncMock())
            with self.assertRaises(Blocked):
                await perform(None,resolver,AtomicAction(action=kind,target='field',value='value'))
            resolver.click_fallback.assert_not_awaited()

    def test_unknown_fault_exit_two_before_browser(self):
        for command in ['run','suite']:
            with patch('test_agent.runner.async_playwright') as browser,contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(main([command,'unused','--locators','unused','--fault','unknown']),2)
            browser.assert_not_called()

    def test_check_only_or_undeclared_target_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            folder,_,_,_=layer_folder(Path(temp))
            plan,source=load_plan(folder)
            source['vocabulary']=json.loads((ROOT/'cases/osm/vocabulary.json').read_text())
            for fault in ['broken-locator:map layers panel','broken-locator:undeclared','vision-click:map layer selector']:
                with self.assertRaises(ValueError):
                    validate_fault_targets([fault],[(plan,source)])

    async def test_interception_exact_hosts_methods_and_tile_subdomains(self):
        for url,method,fault,expected in [
                ('https://a.tile.openstreetmap.org/1/2/3.png','GET','blank-tiles','abort'),
                ('https://tile.openstreetmap.org/1/2/3.png','GET','blank-tiles','abort'),
                ('https://www.openstreetmap.org/directions','GET','directions-503','fulfill'),
                ('https://tile.openstreetmap.org.evil.test/x','GET','blank-tiles',None),
                ('https://www.openstreetmap.org/directions','POST','directions-503',None)]:
            route=SimpleNamespace(request=SimpleNamespace(url=url,method=method),abort=AsyncMock(),fulfill=AsyncMock())
            self.assertEqual(await intercept_fault(route,[fault]),expected is not None)
            if expected:
                getattr(route,expected).assert_awaited_once()
            if expected=='fulfill':
                self.assertEqual(route.fulfill.call_args.kwargs['status'],503)

    async def test_claude_coordinate_request_has_resize_guard_and_no_expected_values(self):
        provider=ClaudeVision(api_key='fake',model='test')
        with patch('test_agent.verification.vision_providers.urlopen',return_value=http_reply()) as send:
            await provider.locate_click(b'png','Opens the layers drawer')
        body=json.loads(send.call_args.args[0].data)
        self.assertEqual(body['messages'][0]['content'][0]['transformations'],{'oversized_image':'error'})
        self.assertIn('absolute pixel',body['system'])
        self.assertNotIn('Hamburg',json.dumps(body))


@unittest.skipUnless(any(p.is_file() for p in (ROOT/'.browsers').rglob('chrome-headless-shell')),'Project Chromium missing')
class FaultBrowserTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        os.environ.setdefault('PLAYWRIGHT_BROWSERS_PATH',str(ROOT/'.browsers'))
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.folder,_,_,_=layer_folder(self.root)
        source=json.loads((self.folder/'source.json').read_text())
        vocabulary=ROOT/'cases/osm/vocabulary.json'
        source.update(vocabulary=json.loads(vocabulary.read_text()),vocabulary_file=str(vocabulary))
        (self.folder/'source.json').write_text(json.dumps(source))
        self.specs=json.loads((ROOT/'cases/osm/locators.json').read_text())
        self.path=self.root/'locators.json'
        self.path.write_text(json.dumps(self.specs))

    async def layers(self,provider,*,fault='vision-click:layers control',html=None,planner=None):
        body=html or (ROOT/'tests/fixtures/fake_layers.html').read_text()
        body=body.replace('<a href="#"','<a style="position:absolute;left:100px;top:100px;padding:10px" href="#"')
        async def intercept(route):
            await route.fulfill(status=200,content_type='text/html',body=body)
        return await run_case(self.folder,self.path,ROOT,output_root=self.root/'runs',route_handler=intercept,
            vision_provider=provider,timeout=150,faults=[fault] if fault else [],locator_planner=planner or FakePlanner())

    async def test_normal_resolution_then_failed_heal_can_fall_back_once(self):
        self.specs['layers control']['name']='Obsolete Layers'
        self.path.write_text(json.dumps(self.specs))
        planner=FakePlanner(dict(locator=dict(strategy='text',value='Missing'),rationale='not found'))
        provider=FakeClick()
        result=await self.layers(provider,fault=None,planner=planner)
        self.assertEqual(result.status,'PASSED',result.model_dump())
        self.assertEqual(result.steps[1].actions[0]['locator_source'],'vision')
        self.assertEqual(len(planner.calls),1)
        self.assertEqual(len(provider.calls),1)

    async def test_forced_vision_click_passes_with_effect_and_evidence(self):
        provider=FakeClick()
        original=self.path.read_bytes()
        result=await self.layers(provider)
        self.assertEqual(result.status,'PASSED',result.model_dump())
        action=result.steps[1].actions[0]
        self.assertEqual(action['locator_source'],'vision')
        self.assertEqual((result.vision_click_attempts,result.vision_click_successes),(1,1))
        self.assertTrue(result.outcome_as_designed)
        self.assertEqual(len(provider.calls),1)
        folder=Path(result.output_directory)/'vision-click/click-1'
        for name in ['viewport.png','click-point.png','request.json','response.json','decision.json']:
            self.assertTrue((folder/name).exists())
        self.assertEqual(self.path.read_bytes(),original)
        self.assertFalse((self.root/'locators.cache.json').exists())

    async def test_rejected_points_never_click(self):
        for changes,code in [({'found':False},'VISION_CLICK_INCONCLUSIVE'),
                ({'confidence':.89},'VISION_CLICK_INCONCLUSIVE'),
                ({'x':1280.0},'VISION_CLICK_COORDINATES'),({'y':-1.0},'VISION_CLICK_COORDINATES')]:
            result=await self.layers(FakeClick(**changes))
            self.assertEqual(result.status,'BLOCKED',result.model_dump())
            self.assertEqual(result.steps[1].details['code'],code)
            self.assertEqual(result.vision_click_attempts,0)

    async def test_click_without_effect_blocks_and_does_not_retry(self):
        provider=FakeClick(x=500.0,y=500.0)
        result=await self.layers(provider)
        self.assertEqual(result.status,'BLOCKED')
        self.assertEqual(result.steps[1].details['code'],'VISION_CLICK_NO_EFFECT')
        self.assertEqual((result.vision_click_attempts,result.vision_click_successes),(1,0))
        self.assertEqual(len(provider.calls),1)

    async def test_already_visible_effect_or_noncoordinate_provider_blocks(self):
        provider=FakeClick()
        html=(ROOT/'tests/fixtures/fake_layers.html').read_text().replace('id="map-ui" hidden','id="map-ui"')
        result=await self.layers(provider,html=html)
        self.assertEqual(result.steps[1].details['code'],'VISION_CLICK_EFFECT_ALREADY_VISIBLE')
        self.assertEqual(provider.calls,[])
        result=await self.layers(FakeVision())
        self.assertEqual(result.steps[1].details['code'],'VISION_CONFIG')
        self.assertEqual(result.vision_click_attempts,0)

    async def test_missing_declaration_or_human_effect_forbids_fallback(self):
        for missing in ['declaration','effect']:
            specs=json.loads(json.dumps(self.specs))
            if missing=='declaration':
                del specs['layers control']['vision_click_effect']
                del specs['layers control']['vision_click']
            else:
                del specs['map layers panel']
            self.path.write_text(json.dumps(specs))
            provider=FakeClick()
            result=await self.layers(provider)
            self.assertEqual(result.status,'BLOCKED')
            self.assertEqual(provider.calls,[])

    async def test_successful_human_action_never_uses_vision_and_missing_check_never_falls_back(self):
        del self.specs['map layers panel']
        self.path.write_text(json.dumps(self.specs))
        provider=FakeClick()
        # Broken locator heals only layers control; missing map layers panel check stays BLOCKED.
        result=await self.layers(provider,fault='broken-locator:layers control')
        self.assertEqual(result.status,'BLOCKED')
        self.assertEqual(result.steps[1].actions[0]['locator_source'],'healed')
        self.assertEqual(result.steps[1].checks[0].actual['code'],'NO_LOCATOR')
        self.assertEqual(provider.calls,[])

    async def test_broken_locator_uses_private_cache_even_if_shared_cache_exists(self):
        shared=self.root/'locators.cache.json'
        shared.write_text('{"unrelated":"preserve"}')
        result=await self.layers(FakeClick(),fault='broken-locator:layers control')
        self.assertEqual(result.status,'PASSED',result.model_dump())
        self.assertTrue(result.outcome_as_designed)
        self.assertEqual(result.steps[1].actions[0]['locator_source'],'healed')
        self.assertEqual(shared.read_text(),'{"unrelated":"preserve"}')
        self.assertTrue((Path(result.output_directory)/'fault-cache/locators.cache.json').exists())

    async def route_fault(self,fault):
        folder=translation_folder(self.root/'route')
        declare_vision(folder)
        path=self.root/'route-locators.json'
        path.write_bytes((ROOT/'tests/fixtures/osm_locators.json').read_bytes())
        html=(ROOT/'tests/fixtures/fake_osm.html').read_text()
        if fault=='directions-503':
            html=html.replace('showDirections(); return false;',"fetch('/directions'); return false;")
        async def intercept(route):
            await route.fulfill(status=200,content_type='text/html',body=html)
        provider=FakeVision(route_line='unclear',start_marker_city='unclear')
        result=await run_case(folder,path,ROOT,output_root=self.root/'runs',route_handler=intercept,
                             vision_provider=provider,timeout=150,faults=[fault])
        return result,provider

    async def test_blank_tiles_unclear_blocks_but_duration_still_runs(self):
        result,provider=await self.route_fault('blank-tiles')
        self.assertEqual(result.status,'BLOCKED',result.model_dump())
        self.assertEqual(result.steps[3].checks[-1].actual['code'],'VISION_INCONCLUSIVE')
        self.assertEqual(result.steps[4].status,'PASSED')
        self.assertTrue(result.outcome_as_designed)

    async def test_directions_503_stops_steps_and_does_not_call_vision(self):
        result,provider=await self.route_fault('directions-503')
        self.assertEqual(result.status,'BLOCKED')
        self.assertIn('GET /directions → 503',result.reason)
        self.assertTrue(all(s.status=='NOT_RUN' for s in result.steps[2:]))
        self.assertTrue(result.outcome_as_designed)
        self.assertEqual(provider.calls,0)
