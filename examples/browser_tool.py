"""Day 1: browser lifecycle and one deterministic search-box check."""

import argparse
import asyncio
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from playwright.async_api import async_playwright, expect

ROOT = Path(__file__).resolve().parents[1]
# Use the project-local browser installation when present.
if (ROOT / ".browsers").exists():
    os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", str(ROOT / ".browsers"))
OSM_URL = "https://www.openstreetmap.org/"
PRACTICE_HTML = """<!doctype html><html lang="en"><title>Day 1 practice</title>
<body><h1>Local search-box practice</h1>
<label for="query">Search</label><input id="query" placeholder="Search">
<p>This fixture checks typing only; it does not simulate OSM search results.</p>
</body></html>"""


async def check_search_box(*, offline: bool = False, headed: bool = False) -> dict:
    """Locate one textbox, fill Hamburg, verify its value, and save evidence.

    The locator is deliberately predefined for Day 1. AI locator discovery
    and route-result assertions will be separate later milestones.
    """
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    output = ROOT / "artifacts" / run_id
    output.mkdir(parents=True)
    result = {"run_id": run_id, "mode": "local_fixture" if offline else "osm",
              "status": "BLOCKED", "url": None, "locator": {
                  "strategy": "placeholder", "value": "Search", "exact": True, "visible": True},
              "expected": "Hamburg", "actual": None,
              "screenshot": None, "error": None}

    browser = context = page = None
    try:
        async with async_playwright() as playwright:
            try:
                # browser = process; context = isolated session; page = tab.
                browser = await playwright.chromium.launch(headless=not headed)
                context = await browser.new_context(locale="en-GB",
                                                    viewport={"width": 1280, "height": 800})
                page = await context.new_page()
                page.set_default_timeout(15_000)
                if offline:
                    await page.set_content(PRACTICE_HTML)
                else:
                    response = await page.goto(OSM_URL, wait_until="domcontentloaded", timeout=30_000)
                    if response is None or not response.ok:
                        raise RuntimeError(f"Page load failed: HTTP {response.status if response else 'no response'}")
                result["url"] = page.url

                # A locator is a rule, not a stored DOM element.
                # OSM includes a second Search field in its responsive layout.
                search_box = page.get_by_placeholder("Search", exact=True).filter(visible=True)
                await expect(search_box).to_have_count(1)
                await expect(search_box).to_be_visible()
                await expect(search_box).to_be_editable()
                await search_box.fill("Hamburg")
                await expect(search_box).to_have_value("Hamburg")
                result["actual"] = await search_box.input_value()
                result["status"] = "PASS"
            except AssertionError as exc:
                result.update(status="FAIL", error=str(exc))
            except Exception as exc:
                result.update(status="BLOCKED", error=f"{type(exc).__name__}: {exc}")
            finally:
                # Capture evidence BEFORE closing the isolated session.
                if page is not None and not page.is_closed():
                    try:
                        screenshot = output / "search-box.png"
                        await page.screenshot(path=str(screenshot))
                        result["screenshot"] = str(screenshot)
                    except Exception as exc:
                        result["evidence_error"] = f"{type(exc).__name__}: {exc}"
                try:
                    if context is not None:
                        await context.close()
                finally:
                    if browser is not None:
                        await browser.close()
    except Exception as exc:
        result.update(status="BLOCKED", error=f"{type(exc).__name__}: {exc}")
    finally:
        (output / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


def arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--offline", action="store_true", help="Use a local practice page instead of OSM")
    parser.add_argument("--headed", action="store_true", help="Show the browser window")
    return parser.parse_args()


if __name__ == "__main__":
    args = arguments()
    outcome = asyncio.run(check_search_box(offline=args.offline, headed=args.headed))
    print(json.dumps(outcome, ensure_ascii=False, indent=2))
    raise SystemExit(0 if outcome["status"] == "PASS" else 1)
