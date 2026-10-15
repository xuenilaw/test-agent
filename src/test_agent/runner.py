"""Single-case deterministic Runner with unconditional cleanup and evidence."""

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from dotenv import load_dotenv
from playwright.async_api import async_playwright
from test_agent.plan_loader import load_plan
from test_agent.schemas.results import CaseResult, CheckResult, StepResult
from test_agent.tools.dom import Blocked, Resolver, perform, capture_map
from test_agent.verification.checks import verify


async def run_case(folder: Path, locators: Path, project_root: Path, *, headed=False,
                   output_root: Path | None = None, route_handler=None, timeout=15_000,
                   vision_provider=None, skip_vision=False):
    # Input errors propagate to the CLI as exit 2, before async_playwright starts.
    plan, source = load_plan(folder)
    resolver = Resolver.from_file(locators)
    declared = (source.get("contract") or {}).get("vision_checks", [])
    if declared and not skip_vision and vision_provider is None:
        from test_agent.verification.vision_providers import provider_from_env, VisionError, UnavailableVision
        load_dotenv(project_root / ".env")
        try:
            vision_provider = provider_from_env()
        except VisionError as exc:
            vision_provider = UnavailableVision(exc)
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
    blocked_vision_reasons = []
    for step, record in zip(plan.steps, result.steps):
        record.checks.extend(CheckResult(kind=v["kind"], target="vision map", expected={
            "requirement": v["requirement"], "min_confidence": v["min_confidence"]})
            for v in declared if v["step"] == step.source_step)

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
                    stop_case = False
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
                                stop_case = True
                                break
                        record.screenshot = await screenshot(f"step-{step.source_step}.png")
                        if not stop_case:
                            from test_agent.verification.vision import verify_route_image, VisionError
                            for index, definition in enumerate(v for v in declared if v["step"] == step.source_step):
                                image = screenshots / f"route-{step.source_step}-{index}.png"
                                capture_error = None
                                try:
                                    await capture_map(page, resolver, image)
                                except Exception:
                                    capture_error = VisionError("CONFIG", fields=["vision_map_screenshot"])
                                visual = await verify_route_image(image, source["contract"], vision_provider,
                                    output / "vision" / f"step-{step.source_step}-{index}", definition=definition,
                                    full_image_path=record.screenshot, skip=skip_vision, capture_error=capture_error)
                                record.checks[len(step.checks) + index] = visual
                                result.route_geometry_verified = visual.status == "PASSED"
                                for checked in record.checks[:len(step.checks)]:
                                    if checked.kind == "route_connects":
                                        checked.actual["route_geometry_verified"] = result.route_geometry_verified
                                if visual.status != "PASSED":
                                    label = f"Step {step.source_step} {definition['kind']}: {visual.reason}"
                                    record.reason = "; ".join(filter(None, [record.reason, label]))
                                    record.status, record.details = visual.status, visual.actual
                                    if visual.status == "FAILED":
                                        stop_case = True
                                        break
                                    blocked_vision_reasons.append(label)
                    except Exception as exc:
                        record.status = "BLOCKED"
                        record.reason = str(exc) if isinstance(exc, Blocked) else type(exc).__name__
                        record.details = getattr(exc, "details", {})
                        stop_case = True
                    if record.screenshot is None:
                        record.screenshot = await screenshot(f"step-{step.source_step}.png")
                    if stop_case:
                        result.status = record.status
                        result.reason = "; ".join(dict.fromkeys([*blocked_vision_reasons, record.reason]))
                        break
                else:
                    result.status = "BLOCKED" if blocked_vision_reasons else "PASSED"
                    result.reason = "; ".join(blocked_vision_reasons) or None
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
        visuals = [c for s in result.steps for c in s.checks if c.kind == "route_geometry"]
        result.route_geometry_verified = bool(visuals) and all(c.status == "PASSED" for c in visuals)
        (output / "results.json").write_text(result.model_dump_json(indent=2), encoding="utf-8")
    return result
