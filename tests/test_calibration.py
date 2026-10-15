import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock
from types import SimpleNamespace
from test_executor import ROOT
from test_agent.verification.calibration import totals, rescore, summarize, run_calibration, load_labels
from test_agent.verification.vision import VisualObservation, decide
from test_agent.verification.vision_providers import VisionError
from test_vision import FakeVision
from test_agent.tools.dom import capture_map
from test_agent.verification.calibration_capture import capture_set


class CalibrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_capture_excludes_overlay_and_never_overwrites_frozen_set(self):
        page=SimpleNamespace(screenshot=AsyncMock())
        map_loc=SimpleNamespace(bounding_box=AsyncMock(return_value=dict(x=0,y=55,width=1280,height=745)))
        side_loc=SimpleNamespace(bounding_box=AsyncMock(return_value=dict(x=0,y=55,width=350,height=745)))
        resolver=SimpleNamespace(entries={'vision sidebar':True},resolve=AsyncMock(side_effect=[(map_loc,None),(side_loc,None)]))
        clip=await capture_map(page,resolver,Path('map.png'))
        self.assertEqual(clip,dict(x=350,y=55,width=930,height=745))
        self.assertEqual(page.screenshot.call_args.kwargs['clip'],clip)
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);(root/'labels.json').write_text('[]')
            with self.assertRaisesRegex(ValueError,'already exists'):
                await capture_set(root,Path('unused'),ROOT)

    def records(self):
        obs=FakeVision().observation
        rows=[]
        for i,(expected,ideal,verdict,confidence,status,code) in enumerate([
            ('PASS','PASSED','match',.89,'BLOCKED','VISION_INCONCLUSIVE'),
            ('NOT_PASS','FAILED','match',.91,'PASSED',None),
            ('NOT_PASS','FAILED','mismatch',.94,'FAILED',None),
            ('NOT_PASS','FAILED',None,None,'BLOCKED','VISION_HTTP')]):
            rows.append(dict(image=str(i)+'.png',expected=expected,ideal=ideal,status=status,code=code,
                requirement={'origin':'Hamburg','destination':'Berlin'},
                observation={**FakeVision(verdict=verdict).observation,'confidence':confidence} if verdict else None,
                model_summary='Example',latency_ms=(i+1)*10,model='served-model',
                usage={'input_tokens':(i+1)*100,'output_tokens':(i+1)*10} if verdict else {}))
        return rows

    def test_arithmetic_and_threshold_replay(self):
        records=self.records(); summary=summarize(records); t=summary['totals']
        self.assertEqual(t['false_pass'],1); self.assertEqual(t['missed_pass'],1)
        self.assertAlmostEqual(t['correct_failed_rate'],1/3)
        self.assertEqual(t['blocked_rate'],.5)
        self.assertEqual(summary['performance']['latency_p50_ms'],25)
        self.assertEqual(summary['performance']['latency_p95_ms'],38.5)
        self.assertEqual(summary['performance']['mean_input_tokens_per_attempt'],150)
        self.assertEqual(rescore(records,.85)['missed_pass'],0)
        self.assertEqual(rescore(records,.95)['false_pass'],0)
        self.assertEqual(rescore(records,.95)['error_codes']['VISION_HTTP'],1)
        self.assertFalse(t['ready_for_clef'])

    def test_pure_decision_threshold_boundary_and_no_mutation(self):
        obs=VisualObservation.model_validate({**FakeVision().observation,'confidence':.9})
        original=obs.model_dump()
        self.assertEqual(decide(obs,{'origin':'Hamburg','destination':'Berlin'},.9)[0],'PASSED')
        self.assertEqual(decide(obs,{'origin':'Hamburg','destination':'Berlin'},.95)[0],'BLOCKED')
        self.assertEqual(original,obs.model_dump())

    async def test_offline_run_counts_error_and_saves_report(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp); images=root/'images';images.mkdir()
            labels=[]
            for name,expected,ideal in [('correct.png','PASS','PASSED'),('wrong.png','NOT_PASS','FAILED')]:
                (images/name).write_bytes(b'\x89PNG\r\n\x1a\n')
                labels.append(dict(file=name,route_shown='Example',requirement={'origin':'Hamburg','destination':'Berlin'},
                    expected=expected,ideal=ideal,why='human label'))
            (root/'labels.json').write_text(json.dumps(labels))
            provider=FakeVision()
            good=await provider.observe(b'')
            bad=await FakeVision(verdict='mismatch').observe(b'')
            provider.observe=AsyncMock(side_effect=[good,VisionError('HTTP',http_status=429),bad,bad])
            contract=json.loads((ROOT/'cases/osm/contracts.json').read_text())['OSM-001']
            output,report=await run_calibration(root,provider=provider,contract=contract,project_root=root,runs=2)
            saved=json.loads((output/'results.json').read_text())
            self.assertEqual(provider.observe.await_count,4)
            self.assertEqual(saved['summary']['totals']['missed_pass'],1)
            self.assertEqual(saved['summary']['totals']['false_pass'],0)
            self.assertEqual(saved['summary']['totals']['error_codes']['VISION_HTTP'],1)
            self.assertIn('Threshold (same observations)',report)
            self.assertTrue((output/'responses/correct/2/response.json').exists())

    def test_bad_labels_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);(root/'images').mkdir()
            label=dict(file='unknown.png',route_shown='Example',requirement={'origin':'Hamburg','destination':'Berlin'},
                       expected='PASS',ideal='PASSED',why='human')
            (root/'labels.json').write_text(json.dumps([label]))
            with self.assertRaisesRegex(ValueError,'Unknown image'):
                load_labels(root)
            (root/'images/unknown.png').write_bytes(b'\x89PNG\r\n\x1a\n')
            label['expected']='anything'
            (root/'labels.json').write_text(json.dumps([label]))
            with self.assertRaises(ValueError):
                load_labels(root)
