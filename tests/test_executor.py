"""Offline execution checks; browser tests need an installed Chromium."""

import contextlib
import io
import json
import os
import tempfile
import unittest
from browser_support import chromium_available
from pathlib import Path
from unittest.mock import patch
from test_agent.cli import main
from test_agent.plan_loader import load_plan
from test_agent.readers.excel import read_case
from test_agent.runner import run_case
from test_agent.tools.dom import Blocked, Resolver, perform
from test_agent.schemas.plan import AtomicAction
from test_agent.verification.checks import parse_duration

ROOT = Path(__file__).resolve().parents[1]


def translation_folder(root):
    folder = root / "translation" / "cases" / "OSM-001"
    folder.mkdir(parents=True)
    fixture = json.loads((ROOT / "tests/fixtures/osm_translation.json").read_text())
    contract_file = ROOT / "cases/osm/contracts.json"
    # Deterministic executor fixtures deliberately declare no visual requirement.
    contract = json.loads(contract_file.read_text())["OSM-001"]
    contract["vision_checks"] = []
    contract_file = root / "contracts.json"
    contract_file.write_text(json.dumps({"OSM-001": contract}))
    source = {"case": read_case(ROOT / "cases/osm/WBS_testcase1_osm.xlsx", "OSM-001"),
              "contract": contract,
              "contract_file": str(contract_file), "application_url": "https://www.openstreetmap.org/"}
    for name, data in (("plan", fixture["plan"]), ("source", source),
                       ("validation", {"status": "VALIDATED", "errors": [], "contract_applied": True})):
        (folder / f"{name}.json").write_text(json.dumps(data))
    return folder


class InputAndDurationTests(unittest.TestCase):
    def test_duration_formats_and_exact_boundary(self):
        for text, minutes in (("2:45",165),("3:00",180),("59 min",59),("0:59",59),("Time: 2:45",165)):
            with self.subTest(text=text):
                self.assertEqual(parse_duration(text), minutes)
        self.assertFalse(parse_duration("3:00") < 180)
        for text in ("garbage", "2:99", "", "-1:00"):
            with self.subTest(text=text), self.assertRaises(Blocked):
                parse_duration(text)

    def test_rejected_folder_never_launches_browser(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = translation_folder(Path(temp))
            (folder / "validation.json").write_text('{"status":"REJECTED"}')
            with patch("test_agent.runner.async_playwright") as browser, contextlib.redirect_stdout(io.StringIO()):
                code = main(["run", str(folder), "--locators", str(ROOT / "tests/fixtures/osm_locators.json")])
            self.assertEqual(code, 2)
            browser.assert_not_called()

    def test_modified_plan_rejected_and_changed_contract_is_stale(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = translation_folder(Path(temp))
            data = json.loads((folder / "plan.json").read_text())
            data["steps"][4]["checks"][0]["value"] = 240
            (folder / "plan.json").write_text(json.dumps(data))
            with self.assertRaisesRegex(ValueError, "Loaded plan rejected"):
                load_plan(folder)
            source = json.loads((folder / "source.json").read_text())
            source["contract"]["limit_minutes"] = 240
            (folder / "source.json").write_text(json.dumps(source))
            with self.assertRaisesRegex(ValueError, "Contract requirements changed"):
                load_plan(folder)

    def test_locator_config_rejects_code_and_alias_collision(self):
        with self.assertRaises(ValueError):
            Resolver({"bad": {"strategy": "eval", "value": "anything"}})
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            Resolver({"one": {"strategy":"css","value":"body","aliases":["two"]},
                      "two": {"strategy":"css","value":"body"}})

    def test_malformed_plan_never_launches_browser(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = translation_folder(Path(temp))
            (folder / "plan.json").write_text('{"case_id":"OSM-001"}')
            with patch("test_agent.runner.async_playwright") as browser, contextlib.redirect_stdout(io.StringIO()):
                code = main(["run", str(folder), "--locators", str(ROOT / "tests/fixtures/osm_locators.json")])
            self.assertEqual(code, 2)
            browser.assert_not_called()

    def test_changed_workbook_requirements_are_stale(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = translation_folder(Path(temp))
            current = json.loads((folder / "source.json").read_text())["case"]
            current["expected"][4]["text"] = "Under 4 hours"
            with patch("test_agent.plan_loader.read_case", return_value=current), \
                    self.assertRaisesRegex(ValueError, "Workbook requirements changed"):
                load_plan(folder)

    def test_old_amendment_source_requires_regeneration(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = translation_folder(Path(temp))
            (folder / "source.json").write_text('{"effective":{}}')
            with self.assertRaisesRegex(ValueError, "Old translation source format"):
                load_plan(folder)


@unittest.skipUnless(chromium_available(),
                     "Project Chromium not installed: run playwright install chromium")
class BrowserExecutorTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", str(ROOT / ".browsers"))
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.folder = translation_folder(self.root)
        self.specs = json.loads((ROOT / "tests/fixtures/osm_locators.json").read_text())
        self.html = (ROOT / "tests/fixtures/fake_osm.html").read_text()

    async def execute(self):
        locators = self.root / "locators.json"
        locators.write_text(json.dumps(self.specs))
        async def intercept(route):
            if route.request.url.startswith("https://www.openstreetmap.org/"):
                await route.fulfill(status=200, content_type="text/html", body=self.html)
            else:
                await route.abort()
        return await run_case(self.folder, locators, ROOT, output_root=self.root / "runs",
                              route_handler=intercept, timeout=600)

    async def test_happy_path_writes_results_screenshots_and_trace(self):
        result = await self.execute()
        self.assertEqual(result.status, "PASSED", result.model_dump())
        folder = Path(result.output_directory)
        for file in ("results.json", "plan.json", "source.json", "locators.json", "trace.zip",
                     "screenshots/final.png", "screenshots/step-5.png"):
            self.assertTrue((folder / file).exists(), file)
        self.assertFalse(result.route_geometry_verified)

    async def test_form_not_ready_reports_lazy_fetch_http_status(self):
        self.html = self.html.replace('showDirections(); return false;', "fetch('/directions'); return false;")
        locators=self.root/'locators.json'
        locators.write_text(json.dumps(self.specs))
        requests=[]
        async def intercept(route):
            requests.append(route.request.url)
            if route.request.url=='https://www.openstreetmap.org/directions':
                await route.fulfill(status=503,body='Service unavailable')
            elif route.request.url=='https://www.openstreetmap.org/':
                await route.fulfill(status=200,content_type='text/html',body=self.html)
            else:
                await route.abort()
        result=await run_case(self.folder,locators,ROOT,output_root=self.root/'runs',route_handler=intercept,timeout=300)
        self.assertEqual(result.status,'BLOCKED')
        self.assertEqual(result.steps[1].details['code'],'FORM_NOT_READY')
        self.assertEqual(result.steps[1].details['http_status'],503)
        self.assertIn('GET /directions → 503',result.reason)
        self.assertEqual(requests.count('https://www.openstreetmap.org/directions'),1)

    async def test_duration_failure_and_cleanup(self):
        self.html = self.html.replace('>2:45<', '>3:15<')
        result = await self.execute()
        self.assertEqual(result.status, "FAILED")
        check = result.steps[4].checks[0]
        self.assertEqual(check.actual["parsed_minutes"], 195)
        self.assertEqual(check.actual["raw_text"], "3:15")
        self.assertTrue(all(entry["status"] == "PASSED" and entry["actual"] == "" for entry in result.cleanup))

    async def test_missing_target_blocks_and_leaves_later_steps_not_run(self):
        del self.specs["travel-mode selector"]
        result = await self.execute()
        self.assertEqual(result.status, "BLOCKED")
        self.assertEqual(result.steps[2].reason, "no locator for target 'travel-mode selector'")
        self.assertEqual(result.steps[2].details["code"], "NO_LOCATOR")
        self.assertTrue(all(step.status == "NOT_RUN" for step in result.steps[3:]))

    async def test_ambiguous_locator_reports_count(self):
        self.html = self.html.replace('<input placeholder="From" id="route_from">',
                                      '<input placeholder="From" id="route_from"><input placeholder="From">')
        result = await self.execute()
        self.assertEqual(result.status, "BLOCKED")
        self.assertEqual(result.steps[1].checks[0].actual["count"], 2)

    async def test_unparseable_duration_is_blocked(self):
        self.html = self.html.replace('>2:45<', '>unknown<')
        result = await self.execute()
        self.assertEqual(result.status, "BLOCKED")
        self.assertEqual(result.steps[4].checks[0].actual["code"], "DURATION_FORMAT")

    async def test_exact_three_hours_fails(self):
        self.html = self.html.replace('>2:45<', '>3:00<')
        result = await self.execute()
        self.assertEqual(result.status, "FAILED")

    async def test_submission_no_effect_is_blocked_without_retry(self):
        self.html = self.html.replace('event.preventDefault();',
            'event.preventDefault(); window.enterCount=(window.enterCount||0)+1; if(window.enterCount===1)return;')
        result = await self.execute()
        self.assertEqual(result.status, "BLOCKED")
        self.assertEqual(result.steps[3].details["code"], "SUBMIT_NO_EFFECT")
        self.assertEqual(result.steps[3].actions[2]["attempts"], 1)
        self.assertEqual(result.steps[4].status, "NOT_RUN")

    async def test_delayed_form_initialization_waits_before_filling(self):
        self.html = self.html.replace('}, 50);', '}, 200);')
        result = await self.execute()
        self.assertEqual(result.status, "PASSED", result.model_dump())
        self.assertEqual(result.steps[3].actions[2]["attempts"], 1)

    async def test_radio_value_mismatch_is_blocked_before_click(self):
        from playwright.async_api import async_playwright
        async with async_playwright() as p:
            browser = await p.chromium.launch()
            try:
                page = await browser.new_page()
                await page.set_content(self.html)
                await page.locator('form').evaluate('e => e.hidden=false')
                resolver = Resolver(self.specs)
                action = AtomicAction(action="select", target="travel-mode selector", value="Bicycle")
                with self.assertRaises(Blocked) as error:
                    await perform(page, resolver, action)
                self.assertEqual(error.exception.details["code"], "SELECTION_MISMATCH")
                self.assertFalse(await page.locator('#modes_car').is_checked())
            finally:
                await browser.close()
