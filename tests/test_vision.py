"""Offline fakes verify verdict rules, diagnostics and runner precedence, not model accuracy."""

import contextlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from urllib.error import HTTPError, URLError

from test_executor import ROOT, translation_folder
from test_agent.cli import main
from test_agent.runner import run_case
from test_agent.plan_loader import load_plan
from test_agent.schemas.contracts import RouteContract
from test_agent.verification.vision import GLMVision, ClaudeVision, provider_from_env, verify_route_image, endpoint_matches
from test_agent.verification.vision_providers import VisionError

DEFINITION = dict(step=4, kind="route_geometry", requirement="A continuous Hamburg to Berlin route.", min_confidence=0.85)
CONTRACT = dict(origin="Hamburg", destination="Berlin")


def declare_vision(folder):
    source = json.loads((folder / "source.json").read_text())
    source["contract"]["vision_checks"] = [DEFINITION]
    Path(source["contract_file"]).write_text(json.dumps({"OSM-001": source["contract"]}))
    (folder / "source.json").write_text(json.dumps(source))


class FakeVision:
    provider_name='anthropic'
    def __init__(self, **changes):
        verdict = changes.pop("verdict", "match")
        self.observation = dict(confidence=0.95,
            start_marker_city="Hamburg", end_marker_city="Berlin",
            start_marker_position="on_label", end_marker_position="on_label", route_line="continuous",
            summary="The line connects the two labelled markers.", evidence="Visible map line and endpoint markers.")
        if verdict == "mismatch":
            self.observation["end_marker_city"] = "Munich"
        elif verdict == "uncertain":
            self.observation["end_marker_position"] = "unclear"
        self.observation.update(changes)
        self.calls = 0

    async def observe(self, image):
        self.calls += 1
        self.image = image
        return dict(content=json.dumps(self.observation), provider="fake", model="offline",
                    latency_ms=12, usage={"total_tokens":42})


class FakeHTTP(io.BytesIO):
    status = 200


def http_reply(**changes):
    data = dict(stop_reason="end_turn",model="claude-test", usage={"input_tokens":10},
                content=[{"type":"text","text":"{}"}])
    data.update(changes)
    return FakeHTTP(json.dumps(data).encode())


class VisionTests(unittest.IsolatedAsyncioTestCase):
    async def check(self, provider, **kwargs):
        with tempfile.TemporaryDirectory() as temp:
            image = Path(temp) / "image.png"
            image.write_bytes(b"\x89PNG\r\n\x1a\n")
            evidence = Path(temp) / "evidence"
            result = await verify_route_image(image, CONTRACT, provider, evidence, definition=DEFINITION, **kwargs)
            response = json.loads((evidence / "response.json").read_text())
            return result, response

    async def test_reason_rows_and_strict_rules(self):
        scenarios = [({},"PASSED","Vision PASSED"),
            ({"verdict":"mismatch","confidence":0.85},"FAILED","Vision FAILED"),
            ({"verdict":"mismatch","confidence":0.84},"BLOCKED","0.84 < 0.85"),
            ({"verdict":"uncertain"},"BLOCKED","Vision inconclusive"),
            ({"end_marker_position":"near_other_city"},"BLOCKED","near_other_city"),
            ({"route_line":"broken"},"FAILED","route line is broken"),
            ({"route_line":"none"},"BLOCKED","route_line=none"),
            ({"start_marker_position":"unclear"},"BLOCKED","start marker unclear"),
            ({"start_marker_city":"Hamburg, Germany","end_marker_city":"Berlin, Germany"},"PASSED","Vision PASSED"),
            ({"end_marker_city":"Bremen, Germany"},"FAILED","end city"),
            ({"end_marker_city":"Berlinertordamm"},"FAILED","end city"),
            ({"start_marker_city":"Berlin","end_marker_city":"Hamburg"},"FAILED","start city")]
        for changes, expected, reason in scenarios:
            with self.subTest(changes=changes):
                result, _ = await self.check(FakeVision(**changes))
                self.assertEqual(result.status,expected)
                self.assertIn(reason,result.reason)
                self.assertIn("0.85",result.reason)
                self.assertEqual(result.actual["min_confidence"],0.85)
                self.assertEqual(result.actual["route_geometry_verified"],expected=="PASSED")
                self.assertTrue(result.actual["model_summary"])

    async def test_invalid_json_schema_and_skip_have_saved_response(self):
        for content, code in [("not JSON","INVALID_JSON"), ("{}","SCHEMA"),
                (json.dumps({**FakeVision().observation,"confidence":float("nan")}),"SCHEMA"),
                (json.dumps({**FakeVision().observation,"summary":"x"*201}),"SCHEMA")]:
            provider=SimpleNamespace(observe=AsyncMock(return_value={"content":content}))
            result, response = await self.check(provider)
            self.assertEqual(response["error_code"],"VISION_"+code)
            self.assertIn("No model explanation available",result.reason)
        provider=FakeVision()
        result,response=await self.check(provider,skip=True)
        self.assertEqual(provider.calls,0)
        self.assertEqual(response["error_code"],"VISION_SKIPPED")
        self.assertEqual(result.status,"BLOCKED")

    async def test_judgment_programming_error_is_internal_not_network(self):
        provider=FakeVision()
        with patch("test_agent.verification.vision.endpoint_matches",side_effect=KeyError("SECRET")):
            result,response=await self.check(provider)
        self.assertEqual(result.actual["code"],"VISION_INTERNAL")
        self.assertEqual(response["error_class"],"KeyError")
        self.assertIn("error_class=KeyError",result.reason)
        self.assertNotIn("SECRET",result.model_dump_json())

    async def test_each_transport_error_code_is_safe_and_saved(self):
        cases=[("INCOMPLETE",{"return_value":http_reply(stop_reason="max_tokens")}),
            ("NOT_SINGLE_TEXT",{"return_value":http_reply(content=[{"type":"text","text":"{}"},{"type":"text","text":"{}"}])}),
            ("HTTP",{"side_effect":HTTPError("https://secret.test/SECRET",403,"SECRET",{},None)}),
            ("TIMEOUT",{"side_effect":TimeoutError("SECRET")}),
            ("NETWORK",{"side_effect":URLError("SECRET")}),
            ("INVALID_JSON",{"return_value":FakeHTTP(b"not JSON")}),
            ("SCHEMA",{"return_value":FakeHTTP(b"[]")})]
        for code, options in cases:
            with self.subTest(code=code), patch("test_agent.verification.vision_providers.urlopen",**options):
                result,response=await self.check(ClaudeVision(api_key="SECRET",model="claude-test"))
                self.assertEqual(result.actual["code"],"VISION_"+code)
                self.assertEqual(response["error_code"],"VISION_"+code)
                self.assertIn("latency_ms",response)
                self.assertNotIn("SECRET",json.dumps(response)+result.model_dump_json())
        result,response=await self.check(None)
        self.assertEqual(response["error_code"],"VISION_CONFIG")

    async def test_thinking_prefix_parsed_but_never_logged(self):
        for prefix in ['thinking','redacted_thinking']:
            blocks=[{'type':prefix,'thinking':'PRIVATE_SECRET'},
                    {'type':'text','text':json.dumps(FakeVision().observation)}]
            with patch('test_agent.verification.vision_providers.urlopen',return_value=http_reply(content=blocks)):
                result,response=await self.check(ClaudeVision(api_key='fake',model='claude-test'))
            self.assertEqual(result.status,'PASSED')
            self.assertTrue(response['thinking_present'])
            self.assertEqual(response['block_types'],[prefix,'text'])
            self.assertNotIn('PRIVATE_SECRET',json.dumps(response)+result.model_dump_json())
        with patch('test_agent.verification.vision_providers.urlopen',return_value=http_reply(content=[])):
            result,response=await self.check(ClaudeVision(api_key='fake',model='claude-test'))
        self.assertEqual(response['error_code'],'VISION_NOT_SINGLE_TEXT')

    async def test_sdk_sends_image_and_records_usage(self):
        client=AsyncMock()
        client.chat.completions.create.return_value=SimpleNamespace(
            choices=[SimpleNamespace(finish_reason="stop",message=SimpleNamespace(content="{}"))],
            model="glm-vision",usage=SimpleNamespace(model_dump=lambda:{"total_tokens":123}))
        with patch("test_agent.verification.vision_providers.AsyncOpenAI") as factory:
            factory.return_value.__aenter__=AsyncMock(return_value=client)
            factory.return_value.__aexit__=AsyncMock(return_value=None)
            reply=await GLMVision(api_key="fake",model="glm-vision",base_url="https://example.test/v1").observe(b"png")
            payload=client.chat.completions.create.call_args.kwargs
            self.assertTrue(payload["messages"][1]["content"][1]["image_url"]["url"].startswith("data:image/png;base64,"))
            self.assertNotIn("tools",payload)
            text=payload["messages"][1]["content"][0]["text"]
            self.assertNotIn("requirement",json.loads(text))
            self.assertNotIn("Hamburg",text)
            self.assertNotIn("Berlin",text)
            self.assertEqual(reply["usage"]["total_tokens"],123)
            self.assertEqual(factory.call_args.kwargs["max_retries"],0)
            client.chat.completions.create.return_value.choices[0].finish_reason="length"
            with self.assertRaises(VisionError) as raised:
                await GLMVision(api_key="fake",model="glm-vision",base_url="https://example.test/v1").observe(b"png")
            self.assertEqual(raised.exception.details["finish_reason"],"length")

    async def test_claude_native_image_and_output_budget(self):
        with patch("test_agent.verification.vision_providers.urlopen",return_value=http_reply(model="served-model")) as send:
            reply=await ClaudeVision(api_key="fake",model="claude-test").observe(b"png")
            body=json.loads(send.call_args.args[0].data)
            self.assertEqual(body["messages"][0]["content"][0]["source"]["media_type"],"image/png")
            self.assertEqual(body["max_tokens"],2048)
            self.assertNotIn("tools",body)
            text=body["messages"][0]["content"][1]["text"]
            self.assertNotIn("requirement",json.loads(text))
            self.assertNotIn("Hamburg",text)
            self.assertNotIn("Berlin",text)
            self.assertEqual(reply["http_status"],200)
            self.assertEqual(reply["model"],"served-model")
            self.assertEqual(reply["requested_model"],"claude-test")

    def test_config_error_never_uses_glm_key(self):
        for config in [{"OPENAI_API_KEY":"glm-key","VISION_MODEL":"claude-test"},
                       {"VISION_PROVIDER":"wrong"}, {"VISION_PROVIDER":"glm"}]:
            with patch.dict(os.environ,config,clear=True),self.assertRaises(VisionError) as raised:
                provider_from_env()
            self.assertEqual(raised.exception.code,"CONFIG")

    def test_qualified_requirement_retains_country(self):
        self.assertTrue(endpoint_matches(" Hamburg, Germany ","hamburg, germany"))
        self.assertFalse(endpoint_matches("Hamburg, USA","Hamburg, Germany"))

    def test_contract_rejects_invalid_or_missing_confidence_and_unknown_kind(self):
        contract=json.loads((ROOT / "cases/osm/contracts.json").read_text())["OSM-001"]
        for changes in [{"min_confidence":0.5},{"min_confidence":1.1},{"kind":"free_text"}]:
            with self.subTest(changes=changes),self.assertRaises(ValueError):
                RouteContract.model_validate({**contract,"vision_checks":[{**DEFINITION,**changes}]})
        missing={k:v for k,v in DEFINITION.items() if k!="min_confidence"}
        with self.assertRaises(ValueError):
            RouteContract.model_validate({**contract,"vision_checks":[missing]})
        typed=RouteContract.model_validate(contract)
        with self.assertRaisesRegex(ValueError,"does not exist"):
            typed.validate_case_steps({1,2,3,5})

    def test_contract_change_stales_saved_plan(self):
        with tempfile.TemporaryDirectory() as temp:
            folder=translation_folder(Path(temp))
            source=json.loads((folder / "source.json").read_text())
            contract=source["contract"]
            contract["vision_checks"]=[DEFINITION]
            Path(source["contract_file"]).write_text(json.dumps({"OSM-001":contract}))
            with self.assertRaisesRegex(ValueError,"Contract requirements changed"):
                load_plan(folder)


@unittest.skipUnless(any(p.is_file() for p in (ROOT / ".browsers").rglob("chrome-headless-shell")),"Project Chromium not installed")
class VisionRunnerTests(unittest.IsolatedAsyncioTestCase):
    async def test_default_provider_runs_only_declared_checks_after_dom_pass(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp); folder=translation_folder(root); declare_vision(folder)
            for broken_dom in [False,True]:
                async def intercept(route):
                    html=(ROOT / "tests/fixtures/fake_osm.html").read_text()
                    if broken_dom:
                        html=html.replace('value="car"','value="bicycle"')
                    await route.fulfill(status=200,content_type="text/html",body=html)
                provider=FakeVision()
                with patch("test_agent.verification.vision_providers.provider_from_env",return_value=provider) as factory:
                    result=await run_case(folder,ROOT / "tests/fixtures/osm_locators.json",ROOT,
                        output_root=root,route_handler=intercept,timeout=1500)
                factory.assert_called_once()
                self.assertEqual(provider.calls,0 if broken_dom else 1)
                self.assertEqual(result.status,"BLOCKED" if broken_dom else "PASSED")
                if broken_dom:
                    self.assertEqual(result.steps[3].checks[-1].status,"NOT_RUN")

    async def test_precedence_crop_reasons_and_cleanup(self):
        from struct import unpack
        os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH",str(ROOT / ".browsers"))
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp); folder=translation_folder(root); declare_vision(folder)
            scenarios=[("match","2:45","PASSED","PASSED"),
                ("mismatch","2:45","FAILED","NOT_RUN"),
                ("uncertain","2:45","BLOCKED","PASSED"),
                ("uncertain","3:15","FAILED","FAILED")]
            for verdict,duration,status,last in scenarios:
                with self.subTest(verdict=verdict,duration=duration):
                    async def intercept(route):
                        await route.fulfill(status=200,content_type="text/html",body=
                            (ROOT / "tests/fixtures/fake_osm.html").read_text().replace("2:45",duration))
                    provider=FakeVision(verdict=verdict)
                    result=await run_case(folder,ROOT / "tests/fixtures/osm_locators.json",ROOT,
                        output_root=root,route_handler=intercept,timeout=1500,vision_provider=provider)
                    self.assertEqual(result.status,status)
                    self.assertEqual(result.steps[4].status,last)
                    self.assertEqual(provider.calls,1)
                    self.assertEqual(result.route_geometry_verified,verdict=="match")
                    self.assertTrue(all(e["status"]=="PASSED" for e in result.cleanup))
                    visual=result.steps[3].checks[-1]
                    self.assertTrue(visual.actual["full_screenshot"])
                    self.assertNotEqual(unpack(">II",provider.image[16:24]),(1280,800))
                    if verdict!="match":
                        self.assertIn(visual.reason,result.reason)
                        self.assertIn(visual.reason,result.steps[3].reason)
                    if duration=="3:15":
                        self.assertIn(result.steps[4].reason,result.reason)

    def test_skip_vision_cli_continues_duration_but_never_passes(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp); folder=translation_folder(root); declare_vision(folder)
            # Use fixture intercept through a wrapper around the real runner.
            async def wrapper(*args,**kwargs):
                async def intercept(route):
                    await route.fulfill(status=200,content_type="text/html",body=(ROOT / "tests/fixtures/fake_osm.html").read_text())
                return await run_case(*args,route_handler=intercept,timeout=1500,**kwargs)
            with patch("test_agent.runner.run_case",side_effect=wrapper),patch(
                    "test_agent.verification.vision_providers.provider_from_env") as provider,contextlib.redirect_stdout(io.StringIO()) as printed:
                code=main(["--project-dir",str(ROOT),"run",str(folder),"--locators",
                           str(ROOT / "tests/fixtures/osm_locators.json"),"--output-dir",str(root),"--skip-vision"])
            provider.assert_not_called()
            self.assertEqual(code,1)
            result=json.loads(printed.getvalue())
            self.assertEqual(result["status"],"BLOCKED")
            self.assertEqual(result["steps"][4]["status"],"PASSED")
            self.assertIn("VISION_SKIPPED",result["reason"])
