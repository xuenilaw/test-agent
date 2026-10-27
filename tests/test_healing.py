"""Offline locator proposals, strict rejection, and persistent reuse."""
import json
import os
import tempfile
import unittest
from browser_support import chromium_available
from pathlib import Path

from playwright.async_api import async_playwright

from test_executor import ROOT
from test_suite import layer_folder
from test_agent.planning.locator import SNAPSHOT_LIMIT
from test_agent.runner import run_case
from test_agent.tools.dom import Blocked, perform, capture_map
from test_agent.tools.healing import HealingResolver
from test_agent.schemas.plan import Assertion, AtomicAction
from test_agent.verification.checks import verify


PROPOSAL = dict(locator=dict(strategy='role', role='link', name='Layers'), rationale='Layers link opens the drawer.')


class FakePlanner:
    model_name = 'fake-model'

    def __init__(self, proposal=None):
        self.proposal = proposal if proposal is not None else PROPOSAL
        self.calls = []

    async def propose(self, target, description, snapshot):
        self.calls.append((target, description, snapshot))
        return json.dumps(self.proposal)


@unittest.skipUnless(chromium_available(), 'Project Chromium missing')
class HealingTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        os.environ.setdefault('PLAYWRIGHT_BROWSERS_PATH', str(ROOT/'.browsers'))
        self.pw = await async_playwright().start()
        self.browser = await self.pw.chromium.launch()
        self.page = await self.browser.new_page()
        self.page.set_default_timeout(100)
        await self.page.set_content('<a href="#">Layers</a>')

    async def asyncTearDown(self):
        await self.browser.close()
        await self.pw.stop()

    def resolver(self, planner, specs=None, targets=None):
        return HealingResolver(specs or {}, cache_path=self.root/'locators.cache.json',
            vocabulary=dict(targets=targets if targets is not None else {'layers control':'Opens layers drawer'}),
            planner=planner, case_id='OSM-003', run_id='fake-run', evidence_dir=self.root/'evidence')

    async def test_action_heal_cache_reuse_and_metadata(self):
        planner = FakePlanner()
        resolver = self.resolver(planner)
        await perform(self.page, resolver, AtomicAction(action='click', target='layers control'))
        self.assertEqual(resolver.metadata_for('layers control'), dict(healed=True, locator_source='healed'))
        self.assertEqual(resolver.heal_count, 1)
        cache = json.loads((self.root/'locators.cache.json').read_text())['layers control']
        for key in ('target','locator','case','run_id','model','timestamp','snapshot_hash'):
            self.assertIn(key, cache)
        later = self.resolver(planner)
        await later.resolve_action(self.page, 'layers control')
        self.assertEqual(later.metadata_for('layers control'), dict(healed=False, locator_source='cache'))
        self.assertEqual(len(planner.calls), 1)

    async def test_markdown_fenced_proposal_is_unwrapped(self):
        class FencedPlanner(FakePlanner):
            async def propose(self, target, description, snapshot):
                return '```json\n' + await super().propose(target, description, snapshot) + '\n```'
        resolver = self.resolver(FencedPlanner())
        await perform(self.page, resolver, AtomicAction(action='click', target='layers control'))
        self.assertEqual(resolver.metadata_for('layers control'), dict(healed=True, locator_source='healed'))

    async def test_ambiguous_proposal_blocks_once_and_remaining_steps_not_run(self):
        await self.page.set_content('<a href="#">Layers</a><a href="#">Layers</a>')
        planner = FakePlanner()
        resolver = self.resolver(planner)
        for _ in range(2):
            with self.assertRaises(Blocked) as caught:
                await resolver.resolve_action(self.page, 'layers control')
            self.assertEqual(caught.exception.details['code'], 'HEAL_FAILED')
            self.assertEqual(caught.exception.details['count'], 2)
            self.assertIsNotNone(caught.exception.details['proposal'])
        self.assertEqual(len(planner.calls), 1)
        self.assertFalse((self.root/'locators.cache.json').exists())

    async def test_missing_visible_check_ignores_cache_and_never_heals(self):
        planner = FakePlanner()
        resolver = self.resolver(planner, specs={'layers control':dict(strategy='text',value='Missing control')})
        # Seed a previously accepted action cache pointing to a visible lookalike.
        (self.root/'locators.cache.json').write_text(json.dumps({'layers control':{
            'locator':PROPOSAL['locator'], 'rationale':PROPOSAL['rationale']}}))
        check = await verify(self.page, resolver, Assertion(kind='visible', target='layers control'), None)
        self.assertEqual(check.status, 'BLOCKED')
        self.assertEqual(check.actual['code'], 'LOCATOR_COUNT')
        self.assertFalse(check.healed)
        self.assertIsNone(check.locator_source)
        self.assertEqual(planner.calls, [])

    async def test_prior_action_heal_cannot_change_later_check_or_verification_read(self):
        planner = FakePlanner()
        resolver = self.resolver(planner)
        await perform(self.page, resolver, AtomicAction(action='click',target='layers control'))
        checked = await verify(self.page,resolver,Assertion(kind='visible',target='layers control'),None)
        self.assertEqual(checked.status,'BLOCKED')
        self.assertFalse(checked.healed)
        self.assertIsNone(checked.locator_source)
        with self.assertRaises(Blocked):
            await resolver.resolve(self.page,'layers control')
        self.assertEqual(len(planner.calls),1)

    async def test_submit_no_effect_ignores_cache_and_never_heals(self):
        await self.page.set_content('<input placeholder="To"><div>Directions</div>')
        planner = FakePlanner(dict(locator=dict(strategy='text',value='Directions'),rationale='lookalike'))
        specs = {'request-directions button':dict(strategy='placeholder',value='To',submit_key='Enter',submit_effect_target='route'),
                 'route':dict(strategy='css',value='#directions_route')}
        resolver = self.resolver(planner,specs=specs,targets={'route':'Displayed route'})
        (self.root/'locators.cache.json').write_text(json.dumps({'route':{
            'locator':dict(strategy='text',value='Directions'),'rationale':'old lookalike'}}))
        with self.assertRaises(Blocked) as caught:
            await perform(self.page,resolver,AtomicAction(action='click',target='request-directions button'))
        self.assertEqual(caught.exception.details['code'],'SUBMIT_NO_EFFECT')
        self.assertEqual(planner.calls,[])

    async def test_map_capture_ignores_cache_and_never_heals(self):
        planner = FakePlanner()
        resolver = self.resolver(planner,targets={'vision map':'Map rectangle'})
        (self.root/'locators.cache.json').write_text(json.dumps({'vision map':{
            'locator':PROPOSAL['locator'],'rationale':PROPOSAL['rationale']}}))
        with self.assertRaises(Blocked) as caught:
            await capture_map(self.page,resolver,self.root/'map.png')
        self.assertEqual(caught.exception.details['code'],'NO_LOCATOR')
        self.assertEqual(planner.calls,[])

    async def test_css_and_extra_fields_rejected_and_zero_match_blocked(self):
        for i, proposal in enumerate([
                dict(locator=dict(strategy='css', value='a'), rationale='css'),
                {**PROPOSAL, 'action':'click'},
                dict(locator=dict(strategy='text',value='Absent'),rationale='missing')]):
            planner = FakePlanner(proposal)
            resolver = self.resolver(planner)
            resolver.evidence_dir = self.root/str(i)
            with self.assertRaises(Blocked) as caught:
                await resolver.resolve_action(self.page, 'layers control')
            self.assertEqual(caught.exception.details['code'], 'HEAL_FAILED')
            if i == 2:
                self.assertEqual(caught.exception.details['count'], 0)

    async def test_undeclared_and_ambiguous_human_targets_never_call_planner(self):
        planner = FakePlanner()
        with self.assertRaises(Blocked) as caught:
            await self.resolver(planner, targets={}).resolve_action(self.page, 'layers control')
        self.assertEqual(caught.exception.details['code'], 'NO_LOCATOR')
        await self.page.set_content('<a href="#">Layers</a><a href="#">Layers</a>')
        specs = {'layers control':dict(strategy='role',role='link',name='Layers')}
        with self.assertRaises(Blocked) as caught:
            await self.resolver(planner, specs=specs).resolve_action(self.page, 'layers control')
        self.assertEqual(caught.exception.details['count'], 2)
        self.assertEqual(planner.calls, [])

    async def test_stale_cache_and_broken_human_locator_heal_again(self):
        planner = FakePlanner()
        old = {'layers control':dict(locator=dict(strategy='text',value='Old layers'),rationale='old')}
        (self.root/'locators.cache.json').write_text(json.dumps(old))
        resolver = self.resolver(planner, specs={'layers control':dict(strategy='text',value='Bad locator')})
        await resolver.resolve_action(self.page, 'layers control')
        self.assertEqual(resolver.metadata_for('layers control')['locator_source'], 'healed')
        self.assertEqual(len(planner.calls), 1)
        await resolver.resolve_action(self.page, 'layers control')
        self.assertEqual(resolver.metadata_for('layers control')['locator_source'], 'cache')
        self.assertEqual(len(planner.calls), 1)

    async def test_snapshot_truncated_and_provider_exception_sanitized(self):
        await self.page.set_content('<a href="#">Layers</a><p>' + 'x'*20_000 + '</p>')
        planner = FakePlanner()
        resolver = self.resolver(planner)
        await resolver.resolve_action(self.page, 'layers control')
        self.assertLessEqual(len(planner.calls[0][2]), SNAPSHOT_LIMIT)
        class FailingPlanner(FakePlanner):
            async def propose(self, *args):
                raise RuntimeError('secret-api-key-example')
        (self.root/'locators.cache.json').unlink()
        resolver = self.resolver(FailingPlanner())
        with self.assertRaises(Blocked) as caught:
            await resolver.resolve_action(self.page, 'layers control')
        self.assertNotIn('secret-api-key-example', str(caught.exception))
        self.assertNotIn('secret-api-key-example', (resolver.evidence_dir/'locator-heals.json').read_text())

    async def test_runner_action_heals_then_next_run_uses_cache(self):
        folder, _, _, _ = layer_folder(self.root)
        source_path = folder/'source.json'
        source = json.loads(source_path.read_text())
        vocab = ROOT/'cases/osm/vocabulary.json'
        source.update(vocabulary=json.loads(vocab.read_text()), vocabulary_file=str(vocab))
        source_path.write_text(json.dumps(source))
        specs = json.loads((ROOT/'cases/osm/locators.json').read_text())
        del specs['layers control']
        path = self.root/'locators.json'
        path.write_text(json.dumps(specs))
        original = path.read_bytes()
        planner = FakePlanner()
        async def intercept(route):
            await route.fulfill(status=200,content_type='text/html',body=(ROOT/'tests/fixtures/fake_layers.html').read_text())
        for expected in ['healed', 'cache']:
            result = await run_case(folder, path, ROOT, output_root=self.root/'runs', route_handler=intercept,
                                    timeout=200, locator_planner=planner)
            self.assertEqual(result.status, 'PASSED',result.model_dump())
            entry = result.steps[1].actions[0]
            self.assertEqual(entry['locator_source'], expected)
            self.assertEqual(entry['healed'], expected == 'healed')
            self.assertEqual(result.locator_heals, int(expected == 'healed'))
            used = json.loads((Path(result.output_directory)/'resolved-locators.json').read_text())
            self.assertTrue(any(e['target']=='layers control' and e['locator_source']==expected for e in used))
        self.assertEqual(path.read_bytes(), original)
        self.assertEqual(len(planner.calls), 1)
        # A fresh case with an ambiguous proposal blocks; later source steps stay NOT_RUN.
        (self.root/'locators.cache.json').unlink()
        async def ambiguous(route):
            html = (ROOT/'tests/fixtures/fake_layers.html').read_text().replace('<main', '<a href="#">Layers</a><main')
            await route.fulfill(status=200,content_type='text/html',body=html)
        result = await run_case(folder, path, ROOT, output_root=self.root/'runs', route_handler=ambiguous,
                                timeout=200, locator_planner=FakePlanner())
        self.assertEqual(result.status, 'BLOCKED')
        self.assertEqual(result.steps[1].details['code'], 'HEAL_FAILED')
        self.assertEqual(result.steps[2].status, 'NOT_RUN')
