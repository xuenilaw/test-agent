"""Observable DOM checks; route geometry is explicitly outside this baseline."""

import re
from urllib.parse import urlsplit, parse_qs
from test_agent.schemas.results import CheckResult
from test_agent.tools.dom import Blocked, radio_options
from test_agent.verification.vision import endpoint_matches


def parse_duration(text: str) -> float:
    text = text.strip()
    match = re.fullmatch(r"(?:Time:\s*)?(\d+):(\d{2})(?::(\d{2}))?", text, re.I)
    if match and int(match[2]) < 60 and (match[3] is None or int(match[3]) < 60):
        return int(match[1]) * 60 + int(match[2]) + (int(match[3] or 0) / 60)
    match = re.fullmatch(r"(?:Time:\s*)?(\d+)\s*(?:min|minutes?)", text, re.I)
    if match:
        return int(match[1])
    raise Blocked("unparseable duration", code="DURATION_FORMAT", raw_text=text)


async def verify(page, resolver, check, contract):
    result = CheckResult(kind=check.kind, target=check.target,
                         expected={"operator": check.operator, "value": check.value})
    try:
        loc, _ = await resolver.resolve(page, check.target)
        passed = True
        if check.kind == "visible":
            result.actual = {"raw_text": await loc.inner_text(), "visible": await loc.is_visible()}
            passed = result.actual["visible"]
        elif check.kind == "input_value":
            raw = await loc.input_value()
            result.actual = {"raw_text": raw, "value": raw}
            passed = raw == check.value
        elif check.kind == "selected":
            # Fixed DOM-reading code; never evaluates a string from the locator file.
            selected = await loc.evaluate("""e => {
              const c = e.tagName === 'LABEL' ? e.control : e;
              if (!c) return null;
              if (c.tagName === 'SELECT') return c.selectedOptions[0]?.label ?? null;
              if (c.type === 'radio') return c.checked ? c.value : null;
              return null;
            }""")
            options = await radio_options(loc)
            if options and await loc.evaluate("e => !['LABEL','INPUT'].includes(e.tagName)"):
                checked = [o["label"] for o in options if o["checked"]]
                selected = checked[0] if len(checked) == 1 else None
            result.actual = {"raw_text": selected, "value": selected}
            url = urlsplit(page.url)
            result.actual["url_layers"] = (parse_qs(url.query).get("layers") or parse_qs(url.fragment).get("layers"))
            expected = str(check.value).casefold()
            actual = str(selected).casefold()
            modes = {v.casefold() for v in contract.get("mode_values", [])} if contract else set()
            passed = actual == expected or (actual in modes and expected in modes)
        elif check.kind == "options_present":
            options = await radio_options(loc)
            actual = [o["label"] for o in options]
            missing = sorted(set(check.value) - set(actual))
            result.actual = {"options": actual, "missing": missing,
                             "extra": sorted(set(actual) - set(check.value)),
                             "selected_labels": [o["label"] for o in options if o["checked"]]}
            passed = not missing
        elif check.kind == "route_connects":
            if not contract:
                raise Blocked("route check requires a contract", code="NO_ROUTE_CONTRACT")
            start, _ = await resolver.resolve(page, "starting-point field")
            end, _ = await resolver.resolve(page, "destination field")
            origin, destination = await start.input_value(), await end.input_value()
            result.actual = {"raw_text": await loc.inner_text(), "origin": origin,
                             "destination": destination, "route_geometry_verified": False,
                             "geocoded_fields": origin.casefold() != contract["origin"].casefold()
                                                and destination.casefold() != contract["destination"].casefold()}
            passed = (endpoint_matches(origin, contract["origin"], contract.get("origin_aliases", [])) and
                      endpoint_matches(destination, contract["destination"], contract.get("destination_aliases", [])))
        elif check.kind == "duration_minutes":
            raw = await loc.inner_text()
            result.actual = {"raw_text": raw}
            minutes = parse_duration(raw)
            result.actual["parsed_minutes"] = minutes
            passed = minutes < check.value
        result.status = "PASSED" if passed else "FAILED"
        if not passed:
            result.reason = (f"Duration {result.actual['parsed_minutes']:g} minutes is not less than {check.value} minutes"
                             if check.kind == "duration_minutes" else "actual result does not meet expected result")
    except Exception as exc:
        result.status = "BLOCKED"
        result.reason = str(exc) if isinstance(exc, Blocked) else type(exc).__name__
        result.actual.update(getattr(exc, "details", {}))
    if hasattr(resolver, 'metadata_for'):
        metadata = resolver.metadata_for(check.target)
        result.healed = metadata.get('healed', False)
        result.locator_source = metadata.get('locator_source')
    return result
