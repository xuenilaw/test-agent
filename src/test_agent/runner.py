"""Single-case deterministic Runner with unconditional cleanup and evidence."""

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from playwright.async_api import async_playwright
from test_agent.plan_loader import load_plan
from test_agent.schemas.results import CaseResult, CheckResult, StepResult
from test_agent.tools.dom import Blocked, Resolver, perform
from test_agent.verification.checks import verify


async def run_case(folder: Path, locators: Path, project_root: Path, *, headed=False,
                   output_root: Path | None = None, route_handler=None, timeout=15_000):
    # Input errors propagate to the CLI as exit 2, before async_playwright starts.
    plan, source = load_plan(folder)
    resolver = Resolver.from_file(locators)
    local_browsers = project_root / ".browsers"
    if local_browsers.exists():
        os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", str(local_browsers))
    run_id = "run-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    output = (output_root or project_root / "artifacts") / run_id / "cases" / plan.case_id
    screenshots = output / "screenshots"
    screenshots.mkdir(parents=True)
    for name, data in (("plan", plan.model_dump()), ("source", source), ("locators", resolver.specs)):
        (output / f"{name}.json").write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    result = CaseResult(case_id=plan.case_id, translation_folder=str(folder.resolve()),
                        output_directory=str(output.resolve()),
                        steps=[StepResult(source_step=s.source_step,
                            actions=[{**a.model_dump(), "status": "NOT_RUN"} for a in s.actions],
                            checks=[CheckResult(kind=c.kind, target=c.target,
                                expected={"operator": c.operator, "value": c.value}) for c in s.checks])
                               for s in plan.steps])
    browser = context = page = None
    tracing = False

    async def screenshot(name):
        if page is None or page.is_closed():
            return None
        path = screenshots / name
        try:
            await page.screenshot(path=str(path))
            return str(path.resolve())
        except Exception as exc:
            result.evidence_errors.append(f"{name}: {type(exc).__name__}")

    try:
        async with async_playwright() as playwright:
            try:
                browser = await playwright.chromium.launch(headless=not headed)
                context = await browser.new_context(locale="en-GB", viewport={"width": 1280, "height": 800})
                await context.tracing.start(screenshots=True, snapshots=True, sources=True)
                tracing = True
                page = await context.new_page()
                page.set_default_timeout(timeout)
                if route_handler:
                    await page.route("**/*", route_handler)  # Offline fixtures abort all other hosts.
                for step, record in zip(plan.steps, result.steps):
                    record.status = "PASSED"
                    try:
                        for action, entry in zip(step.actions, record.actions):
                            entry["status"] = "BLOCKED"
                            try:
                                metadata = await perform(page, resolver, action)
                            except Blocked as exc:
                                entry.update(reason=str(exc), **exc.details)
                                raise
                            entry.update(metadata or {})
                            entry["status"] = "PASSED"
                            spec = resolver.entries.get(action.target)
                            if spec and action.action == "click" and spec.submit_key:
                                entry["implementation"] = "press " + spec.submit_key
                        for index, check in enumerate(step.checks):
                            checked = await verify(page, resolver, check, source["contract"])
                            record.checks[index] = checked
                            if checked.status != "PASSED":
                                record.status, record.reason = checked.status, checked.reason
                                record.details = checked.actual
                                break
                    except Exception as exc:
                        record.status = "BLOCKED"
                        record.reason = str(exc) if isinstance(exc, Blocked) else type(exc).__name__
                        record.details = getattr(exc, "details", {})
                    record.screenshot = await screenshot(f"step-{step.source_step}.png")
                    if record.status != "PASSED":
                        result.status, result.reason = record.status, record.reason
                        break
                else:
                    result.status = "PASSED"
            finally:
                # Preserve failure evidence, then cleanup before the session is closed.
                await screenshot("final.png")
                for action in plan.cleanup:
                    entry = {**action.model_dump(), "status": "BLOCKED"}
                    result.cleanup.append(entry)
                    try:
                        if page is None:
                            raise Blocked("browser page unavailable")
                        await perform(page, resolver, action)
                        entry["status"] = "PASSED"
                        if action.action == "fill":
                            loc, _ = await resolver.resolve(page, action.target)
                            entry["actual"] = await loc.input_value()
                    except Exception as exc:
                        entry["reason"] = str(exc) if isinstance(exc, Blocked) else type(exc).__name__
                if context:
                    try:
                        if tracing:
                            await context.tracing.stop(path=str(output / "trace.zip"))
                    except Exception as exc:
                        result.evidence_errors.append(f"trace: {type(exc).__name__}")
                    finally:
                        try:
                            await context.close()
                        except Exception as exc:
                            result.evidence_errors.append(f"context close: {type(exc).__name__}")
                if browser:
                    try:
                        await browser.close()
                    except Exception as exc:
                        result.evidence_errors.append(f"browser close: {type(exc).__name__}")
    except Exception as exc:
        if all(s.status == "NOT_RUN" for s in result.steps):
            result.steps[0].status = "BLOCKED"
            result.steps[0].reason = type(exc).__name__
            result.reason = type(exc).__name__
        else:
            result.evidence_errors.append(type(exc).__name__)
    finally:
        (output / "results.json").write_text(result.model_dump_json(indent=2), encoding="utf-8")
    return result
