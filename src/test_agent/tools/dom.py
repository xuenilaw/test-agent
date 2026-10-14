"""Fixed locator strategies and browser actions. No code from configuration."""

import json
from pathlib import Path
from typing import Literal
from pydantic import model_validator
from test_agent.schemas.plan import StrictModel


class Blocked(Exception):
    def __init__(self, reason: str, **details):
        super().__init__(reason)
        self.details = details


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

    @model_validator(mode="after")
    def arguments(self):
        if self.strategy == "role":
            if not self.role or not self.name:
                raise ValueError("role strategy requires role and name")
        elif not self.value:
            raise ValueError("Locator strategy requires value")
        if self.submit_key and not self.submit_effect_target:
            raise ValueError("submit_key requires submit_effect_target")
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

    async def resolve(self, page, target):
        spec = self.entries.get(target)
        if spec is None:
            raise Blocked(f"no locator for target '{target}'", code="NO_LOCATOR", target=target)
        if spec.strategy == "role":
            loc = page.get_by_role(spec.role, name=spec.name, exact=True)
        elif spec.strategy == "css":
            loc = page.locator(spec.value)
        else:
            method = getattr(page, "get_by_" + spec.strategy)
            loc = method(spec.value) if spec.strategy == "test_id" else method(spec.value, exact=True)
        loc = loc.filter(visible=True)
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


async def perform(page, resolver, action):
    if action.action == "navigate":
        response = await page.goto(action.value, wait_until="domcontentloaded", timeout=30_000)
        if response is None or not response.ok:
            raise Blocked("navigation failed", code="NAVIGATION", http_status=response.status if response else None)
        return
    loc, spec = await resolver.resolve(page, action.target)
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
        await loc.click()
        if spec.ready_selector:
            # The lazy-loaded sidebar template must exist before endpoint listeners are used.
            try:
                await page.locator(spec.ready_selector).wait_for(state="attached")
            except Exception as exc:
                raise Blocked("directions form is not ready", code="FORM_NOT_READY") from exc
    elif action.action == "fill":
        await loc.fill(action.value)
    elif action.action == "press":
        await loc.press(action.value)
    elif action.action == "select":
        tag = await loc.evaluate("e => e.tagName.toLowerCase()")
        if tag == "select":
            await loc.select_option(label=action.value)
        else:
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
