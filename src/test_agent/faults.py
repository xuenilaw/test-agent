"""Explicit demo faults, never persistent edits to case inputs."""
from urllib.parse import urlsplit

SIMPLE = {'blank-tiles', 'directions-503'}
TARGETED = {'broken-locator', 'vision-click'}


class FaultInputError(ValueError):
    pass


def validate_fault_names(faults):
    for fault in faults:
        name, sep, target = fault.partition(':')
        if fault in SIMPLE or name in TARGETED and sep and target.strip():
            continue
        raise FaultInputError('Unknown fault: ' + fault)


def validate_fault_targets(faults, plans):
    validate_fault_names(faults)
    for fault in faults:
        name, sep, target = fault.partition(':')
        if not sep:
            continue
        candidates = [(plan, source) for plan, source in plans
                      if target in (source.get('vocabulary') or {}).get('targets', {})]
        actions = [a for plan, _ in candidates for step in plan.steps for a in step.actions
                   if a.target == target and a.action != 'navigate']
        if not actions or name == 'vision-click' and not any(a.action == 'click' for a in actions):
            raise FaultInputError('Fault target must be a vocabulary action target: ' + target)


def applicable_faults(faults, plan):
    actions = {a.target for step in plan.steps for a in step.actions if a.action != 'navigate'}
    return [f for f in faults if ':' not in f or f.partition(':')[2] in actions]


def fault_expectations(faults):
    return {f: ('BLOCKED' if f in SIMPLE else 'PASSED') for f in faults}


def outcomes_as_designed(result, faults):
    outcomes = {}
    for fault in faults:
        name, _, target = fault.partition(':')
        if name in TARGETED:
            source = 'healed' if name == 'broken-locator' else 'vision'
            matched = any(a.get('target') == target and a.get('locator_source') == source and a.get('status') == 'PASSED'
                          for step in result.steps for a in step.actions)
            outcomes[fault] = result.status == 'PASSED' and matched
        elif name == 'blank-tiles':
            outcomes[fault] = (result.status == 'BLOCKED' and
                any(c.actual.get('code') == 'VISION_INCONCLUSIVE' for s in result.steps for c in s.checks) and
                any(s.source_step == 5 and s.status != 'NOT_RUN' for s in result.steps))
        else:
            outcomes[fault] = (result.status == 'BLOCKED' and
                any(s.source_step == 2 and s.details.get('http_status') == 503 for s in result.steps) and
                all(s.status == 'NOT_RUN' for s in result.steps if s.source_step > 2))
    return outcomes


async def intercept_fault(route, faults):
    request = route.request
    url = urlsplit(request.url)
    host = (url.hostname or '').lower()
    if 'blank-tiles' in faults and (host == 'tile.openstreetmap.org' or
            host.endswith('.tile.openstreetmap.org') or host == 'tile.tracestrack.com' or
            host.endswith('.tile.tracestrack.com')):
        await route.abort()
        return True
    if 'directions-503' in faults and host == 'www.openstreetmap.org' and url.path == '/directions' and request.method == 'GET':
        await route.fulfill(status=503, content_type='text/plain', body='Injected directions unavailability')
        return True
    return False
