"""Fake Decisions requests, pure probability rules, and frozen compression integrity."""
import base64
import hashlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from PIL import Image

from test_executor import ROOT
from test_vision import FakeHTTP, FakeVision, http_reply
from test_agent.verification.clef import ClefDecisions,blind_questions,load_cities
from test_agent.verification.compression import compress_image,freeze_compressed,frozen_image,MAX_BYTES
from test_agent.verification.vision import ClefObservation,decide,verify_route_image
from test_agent.verification.vision_providers import VisionError,ClaudeVision,provider_from_env
from test_agent.verification.calibration import run_calibration,rescore


def png():
    stream=io.BytesIO();Image.new('RGB',(930,745),'white').save(stream,format='PNG');return stream.getvalue()


def answers(start='Hamburg',end='Berlin',line='continuous',probability=.97):
    questions=blind_questions(load_cities())
    result={}
    for key,choice in zip(questions,[start,end,line]):
        options=questions[key]['criteria']
        result[key]=dict(type='choice',choice=choice,confidence=.15,probabilities={
            k:probability if k==choice else (1-probability)/(len(options)-1) for k in options})
    return result


class ClefVisionTests(unittest.IsolatedAsyncioTestCase):
    def test_probability_decisions_and_threshold_replay(self):
        req=dict(origin='Hamburg',destination='Berlin')
        for data,status in [(answers(),'PASSED'),(answers(end='Potsdam'),'FAILED'),
                (answers(end='other'),'FAILED'),(answers(line='broken'),'FAILED'),
                (answers(end='unclear'),'BLOCKED'),(answers(line='none'),'BLOCKED'),
                (answers(probability=.899),'BLOCKED'),(answers(probability=.9),'PASSED')]:
            obs=ClefObservation(answers=data)
            self.assertEqual(decide(obs,req,.90)[0],status)
        obs=ClefObservation(answers=answers(end='München'))
        self.assertEqual(decide(obs,dict(origin='Hamburg',destination='Munich',destination_aliases=['München']),.9)[0],'PASSED')
        # A confident mismatch is failure even when a different answer is unclear.
        self.assertEqual(decide(ClefObservation(answers=answers(start='Bremen',end='unclear')),req,.9)[0],'FAILED')
        record=dict(image='x',expected='PASS',ideal='PASSED',status='BLOCKED',reason='low',code='VISION_INCONCLUSIVE',
                    observation_schema='clef-blind-v1',observation=dict(answers=answers(probability=.86)),requirement=req)
        self.assertEqual(rescore([record],.85)['missed_pass'],0)
        self.assertEqual(record['status'],'BLOCKED')

    async def test_request_shape_and_evidence_exact_jpeg(self):
        provider=ClefDecisions('fake')
        response=dict(answers=answers(),provider='Fake',id='safe',usage=dict(input_tokens=100,cost=.0000042))
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);image=root/'map.png';image.write_bytes(png())
            with patch('test_agent.verification.clef.urlopen',return_value=FakeHTTP(json.dumps(response).encode())) as send:
                checked=await verify_route_image(image,dict(origin='Hamburg',destination='Berlin'),provider,root/'evidence',
                    definition=dict(kind='route_geometry',requirement='Hamburg to Berlin',min_confidence=.9))
            self.assertEqual(checked.status,'PASSED',checked.model_dump())
            body=json.loads(send.call_args.args[0].data)
            self.assertIsInstance(body['state'][0],str)
            self.assertEqual(body['state'][1]['type'],'image_url')
            self.assertEqual(sum(isinstance(item,dict) for item in body['state']),1)
            sent=base64.b64decode(body['state'][1]['image_url']['url'].split(',',1)[1])
            self.assertLess(len(sent),MAX_BYTES)
            self.assertEqual((root/'evidence/sent-image.jpg').read_bytes(),sent)
            self.assertEqual(checked.actual['sha256'],hashlib.sha256(sent).hexdigest())
            self.assertIn('Clef SUCCESS',checked.reason)
            self.assertIn('probabilities',checked.actual['answers']['start_city'])
            self.assertNotIn('Hamburg',body['state'][0])
            self.assertEqual(body['questions'],blind_questions(load_cities()))

    async def test_unknown_option_is_schema_and_click_refused(self):
        bad=answers();bad['end_city']['choice']='Atlantis'
        with patch('test_agent.verification.clef.urlopen',return_value=FakeHTTP(json.dumps(dict(answers=bad)).encode())),self.assertRaises(VisionError) as error:
            await ClefDecisions('fake').observe(png())
        self.assertEqual(error.exception.code,'SCHEMA')
        with self.assertRaises(VisionError) as error:
            await ClefDecisions('fake').locate_click(b'', 'anything')
        self.assertEqual(error.exception.code,'CONFIG')
        with patch.dict(os.environ,dict(VISION_PROVIDER='clef',VISION_MODEL='cloudflare/clef',OPENROUTER_API_KEY='fake')):
            self.assertIsInstance(provider_from_env(),ClefDecisions)

    async def test_claude_uses_exact_jpeg_without_prompt_change(self):
        data,_=compress_image(png())
        with patch('test_agent.verification.vision_providers.urlopen',return_value=http_reply()) as send:
            await ClaudeVision(api_key='fake',model='fake').observe(data)
        body=json.loads(send.call_args.args[0].data)
        source=body['messages'][0]['content'][0]['source']
        self.assertEqual(source['media_type'],'image/jpeg')
        self.assertEqual(base64.b64decode(source['data']),data)

    async def test_frozen_jpeg_integrity_calibration_and_no_overwrite(self):
        source_folder=ROOT/'cases/osm/vision_calibration'
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);(root/'images').mkdir()
            label=json.loads((source_folder/'labels.json').read_text())[0]
            (root/'labels.json').write_text(json.dumps([label]))
            image=root/'images'/label['file'];image.write_bytes(png())
            original=image.read_bytes()
            manifest=freeze_compressed(root)
            self.assertEqual(freeze_compressed(root),manifest)
            self.assertEqual(image.read_bytes(),original)
            contract=json.loads((ROOT/'cases/osm/contracts.json').read_text())['OSM-001']
            output,_=await run_calibration(root,provider=FakeVision(),contract=contract,project_root=ROOT,
                                           runs=1,output_root=root/'runs',image_variant='jpeg')
            record=json.loads((output/'results.json').read_text())['records'][0]
            self.assertEqual(record['image_preprocessing']['quality'],90)
            path=root/'compressed'/next(iter(manifest))
            path.write_bytes(b'tampered')
            with self.assertRaises(ValueError):
                await run_calibration(root,provider=FakeVision(),contract=contract,project_root=ROOT,
                                      runs=1,output_root=root/'runs',image_variant='jpeg')
