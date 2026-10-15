"""Fixed locator strategies and browser actions. No code from configuration."""

import json
import re
from pathlib import Path
from typing import Literal
from urllib.parse import urljoin, urlsplit
from pydantic import model_validator
from test_agent.schemas.plan import StrictModel


class Blocked(Exception):
    def __init__(self, reason: str, **details):
        super().__init__(reason)
        self.details = details


class VisionClickConfig(StrictModel):
    min_confidence: float

    @model_validator(mode="after")
    def threshold(self):
        if self.min_confidence != .90:
            raise ValueError('vision_click.min_confidence must be 0.90')
        return self


class LocatorSpec(StrictModel):
    strategy: Literal["role", "label", "placeholder", "text", "test_id", "css"]
    value: str | None = None
    role: str | None = None
    name: str | None = None
    aliases: list[str] = []
    submit_key: Literal["Enter"] | None = None
    ready_selector: str | None = None
    submit_effect_target: str | None = None
    selection_aliases: list[str] = []
    vision_click_effect: str | None = None
    vision_click: VisionClickConfig | None = None

    @model_validator(mode="after")
    def arguments(self):
        if self.strategy == "role":
            if not self.role or not self.name:
                raise ValueError("role strategy requires role and name")
        elif not self.value:
            raise ValueError("Locator strategy requires value")
        if self.submit_key and not self.submit_effect_target:
            raise ValueError("submit_key requires submit_effect_target")
        if bool(self.vision_click_effect) != (self.vision_click is not None):
            raise ValueError('vision_click_effect and vision_click config must be declared together')
        return self


class Resolver:
    def __init__(self, specs: dict):
        self.specs = specs
        self.entries = {}
        for target, data in specs.items():
            spec = LocatorSpec.model_validate(data)
            for name in [target, *spec.aliases]:
                if name in self.entries:
                    raise ValueError(f"Duplicate locator name/alias: {name}")
                self.entries[name] = spec

    @classmethod
    def from_file(cls, path: Path):
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("Locator file must be an object")
        return cls(data)

    @staticmethod
    def build_locator(page, spec):
        if spec.strategy == "role":
            loc = page.get_by_role(spec.role, name=spec.name, exact=True)
        elif spec.strategy == "css":
            loc = page.locator(spec.value)
        else:
            method = getattr(page, "get_by_" + spec.strategy)
            loc = method(spec.value) if spec.strategy == "test_id" else method(spec.value, exact=True)
        return loc

    async def resolve_action(self, page, target):
        """Action resolution; subclasses may opt into constrained healing here."""
        return await self.resolve(page, target)

    async def resolve(self, page, target):
        spec = self.entries.get(target)
        if spec is None:
            raise Blocked(f"no locator for target '{target}'", code="NO_LOCATOR", target=target)
        loc = self.build_locator(page, spec).filter(visible=True)
        count = await loc.count()
        if count == 0:
            try:
                await loc.wait_for(state="visible")
            except Exception:
                count = await loc.count()
                raise Blocked(f"locator count for '{target}' is {count}", code="LOCATOR_COUNT", count=count, target=target)
            count = await loc.count()
        if count != 1:
            raise Blocked(f"locator count for '{target}' is {count}", code="LOCATOR_COUNT", count=count, target=target)
        return loc, spec


async def capture_map(page, resolver, path):
    """Capture the visible map rectangle, excluding a declared left sidebar overlay."""
    loc, _ = await resolver.resolve(page, "vision map")
    box = await loc.bounding_box()
    if box is None:
        raise Blocked("map has no visible bounds")
    if "vision sidebar" in resolver.entries:
        sidebar, _ = await resolver.resolve(page, "vision sidebar")
        side = await sidebar.bounding_box()
        if (side and side["x"] <= box["x"] and side["y"] < box["y"] + box["height"]
                and side["y"] + side["height"] > box["y"]):
            left = max(box["x"], side["x"] + side["width"])
            box["width"] -= left - box["x"]
            box["x"] = left
    if box["width"] <= 0:
        raise Blocked("sidebar covers map")
    await page.screenshot(path=str(path), clip=box)
    return box


async def radio_options(loc):
    return await loc.evaluate(r"""e => {
      const c = e.tagName === 'LABEL' ? e.control : e;
      const radios = c?.type === 'radio' ? [c] : [...e.querySelectorAll('input[type=radio]')];
      return radios.map(r => ({value:r.value, checked:r.checked,
        label:[...r.labels].map(l => l.textContent.trim().replace(/\s+/g,' ')).filter(Boolean)[0] || r.value}));
    }""")


async def perform(page, resolver, action):
    if action.action == "navigate":
        response = await page.goto(action.value, wait_until="domcontentloaded", timeout=30_000)
        if response is None or not response.ok:
            raise Blocked("navigation failed", code="NAVIGATION", http_status=response.status if response else None)
        return
    try:
        loc, spec = await resolver.resolve_action(page, action.target)
    except Blocked as exc:
        fallback = getattr(resolver, 'click_fallback', None)
        eligible = exc.details.get('code') in {'NO_LOCATOR', 'HEAL_FAILED'} or (
            exc.details.get('code') == 'LOCATOR_COUNT' and exc.details.get('count') == 0)
        if action.action == 'click' and fallback and eligible:
            return await fallback(page, action.target, exc)
        raise
    if action.action == "click":
        # OSM submits directions via Enter in the destination field, not a Go button.
        if spec.submit_key:
            await loc.press(spec.submit_key)
            try:
                await resolver.resolve(page, spec.submit_effect_target)
            except Blocked as exc:
                if exc.details.get("code") != "LOCATOR_COUNT" or exc.details.get("count") != 0:
                    raise
                raise Blocked("directions submission produced no visible result", code="SUBMIT_NO_EFFECT",
                              attempts=1, effect_target=spec.submit_effect_target) from exc
            return {"attempts": 1, "effect_target": spec.submit_effect_target}
        statuses = []
        path = None
        origin = None
        def record_response(response):
            parsed = urlsplit(response.url)
            if (path and (parsed.scheme, parsed.netloc) == origin
                    and parsed.path == path and response.request.method == "GET"):
                statuses.append(response.status)
        if spec.ready_selector:
            href = await loc.get_attribute("href")
            parsed = urlsplit(urljoin(page.url, href)) if href else None
            path = parsed.path if parsed else None
            origin = (parsed.scheme, parsed.netloc) if parsed else None
            page.on("response", record_response)
        try:
            await loc.click()
            if spec.ready_selector:
                # Observe the existing lazy fetch; never send another request or retry.
                try:
                    await page.locator(spec.ready_selector).wait_for(state="attached")
                except Exception as exc:
                    status = next((s for s in reversed(statuses) if s >= 400), None)
                    detail = f": GET {path} → {status}" if status is not None else ""
                    raise Blocked("directions form is not ready" + detail, code="FORM_NOT_READY",
                                  http_status=status, request_path=path) from exc
        finally:
            if spec.ready_selector:
                page.remove_listener("response", record_response)
    elif action.action == "fill":
        await loc.fill(action.value)
    elif action.action == "press":
        await loc.press(action.value)
    elif action.action == "select":
        tag = await loc.evaluate("e => e.tagName.toLowerCase()")
        if tag == "select":
            await loc.select_option(label=action.value)
        else:
            if tag not in {"label", "input"}:
                options = await radio_options(loc)
                matches = [o for o in options if o["label"].casefold() == action.value.casefold()]
                if len(matches) != 1:
                    raise Blocked("requested layer does not match one option", code="SELECTION_MISMATCH", count=len(matches))
                label = loc.locator("label").filter(has_text=re.compile(r"^\s*" + re.escape(action.value) + r"\s*$", re.I)).filter(visible=True)
                if await label.count() != 1:
                    raise Blocked("layer label is ambiguous", code="LOCATOR_COUNT", count=await label.count())
                await label.click()
                return {"selected_label": matches[0]["label"]}
            value = await loc.evaluate("""e => {
              const c = e.tagName === 'LABEL' ? e.control : e;
              return c?.type === 'radio' ? c.value : null;
            }""")
            if value is None:
                raise Blocked("unsupported selection control", code="SELECTION_CONTROL")
            allowed = {value.casefold(), *(v.casefold() for v in spec.selection_aliases)}
            if action.value.casefold() not in allowed:
                raise Blocked("requested selection does not match locator control", code="SELECTION_MISMATCH",
                              requested=action.value, control_value=value)
            if tag == "label":
                await loc.click()
            else:
                await loc.check()
