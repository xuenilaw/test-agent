"""Text-only Decisions smoke transport; no live service needed."""
import contextlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError

from test_agent.verification.clef import DecisionsClient, ENDPOINT, smoke
from test_agent.verification.vision_providers import VisionError
from test_vision import FakeHTTP


QUESTIONS={'traffic_light':dict(type='choice',instructions='Colour?',criteria=dict(red=None,green=None,unclear=None))}


def reply(**changes):
    data=dict(answers={'traffic_light':dict(type='choice',choice='red',probabilities=dict(red=.98,green=.01,unclear=.01),confidence=.95)},
              provider='Cloudflare',id='fake-request',usage=dict(input_tokens=42,output_tokens=0,cost=.000001))
    data.update(changes)
    return FakeHTTP(json.dumps(data).encode())


class ClefSmokeTests(unittest.IsolatedAsyncioTestCase):
    async def test_text_only_decisions_request_shape_and_metadata(self):
        with patch('test_agent.verification.clef.urlopen',return_value=reply()) as send:
            result=await DecisionsClient('private-key-placeholder').request(['The traffic light is red.'],QUESTIONS)
        request=send.call_args.args[0]
        self.assertEqual(request.full_url,ENDPOINT)
        body=json.loads(request.data)
        self.assertEqual(body['model'],'cloudflare/clef')
        self.assertTrue(all(isinstance(item,str) for item in body['state']))
        self.assertNotIn('messages',body)
        self.assertEqual(result['answers']['traffic_light']['choice'],'red')
        self.assertEqual(result['upstream_provider'],'Cloudflare')
        self.assertEqual(result['usage']['input_tokens'],42)
        self.assertNotIn('private-key-placeholder',json.dumps(result))

    async def test_missing_key_blocks_without_request_and_saves_safe_output(self):
        with tempfile.TemporaryDirectory() as temp,patch.dict(os.environ,{},clear=True),patch(
                'test_agent.verification.clef.load_dotenv'),patch('test_agent.verification.clef.urlopen') as send,contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(await smoke(Path(temp)),1)
            send.assert_not_called()
            result=json.loads(next(Path(temp).glob('artifacts/clef-smoke-*/result.json')).read_text())
            self.assertEqual(result['code'],'VISION_CONFIG')
            self.assertNotIn('http_status',result)

    async def test_unknown_choice_or_missing_probabilities_rejected(self):
        for answers in [dict(traffic_light=dict(type='choice',choice='blue',probabilities={},confidence=.9)),
                        dict(traffic_light=dict(type='choice',choice='red',confidence=.9)),{}]:
            with patch('test_agent.verification.clef.urlopen',return_value=reply(answers=answers)),self.assertRaises(VisionError) as error:
                await DecisionsClient('fake').request(['red'],QUESTIONS)
            self.assertEqual(error.exception.code,'SCHEMA')

    async def test_http_status_only_no_error_body_and_no_retry(self):
        for status in [401,413,429,503]:
            with patch('test_agent.verification.clef.urlopen',side_effect=HTTPError(ENDPOINT,status,'secret error body',{},None)) as send,self.assertRaises(VisionError) as error:
                await DecisionsClient('fake').request(['red'],QUESTIONS)
            self.assertEqual(error.exception.code,'HTTP')
            self.assertEqual(error.exception.details['http_status'],status)
            self.assertNotIn('secret error body',str(error.exception.details))
            self.assertEqual(send.call_count,1)
