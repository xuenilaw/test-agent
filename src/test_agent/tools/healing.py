"""Actions may use cache/healing; observations use human-reviewed locators only."""
import hashlib
import json
import os
import tempfile
from datetime import datetime, timezone

from test_agent.planning.locator import LocatorProposal, SNAPSHOT_LIMIT
from test_agent.tools.dom import Blocked, LocatorSpec, Resolver


class HealingResolver(Resolver):
    def __init__(self, specs, *, cache_path, vocabulary, planner, case_id, run_id, evidence_dir):
        super().__init__(specs)
        self.cache_path, self.planner = cache_path, planner
        self.targets = (vocabulary or {}).get('targets', {})
        self.case_id, self.run_id = case_id, run_id
        self.evidence_dir = evidence_dir
        self.attempted, self.failures = set(), {}
        self.events, self.metadata, self.used_locators = [], {}, []

    def remember(self, target, spec, source):
        self.metadata[target] = dict(healed=source == 'healed', locator_source=source)
        self.used_locators.append(dict(target=target, locator=spec.model_dump(), **self.metadata[target]))

    @classmethod
    def from_file(cls, path, **kwargs):
        data = json.loads(path.read_text(encoding='utf-8'))
        if not isinstance(data, dict):
            raise ValueError('Locator file must be an object')
        return cls(data, cache_path=path.parent/'locators.cache.json', **kwargs)

    def metadata_for(self, target):
        return self.metadata.get(target, {})

    @property
    def heal_count(self):
        return sum(e.get('status') == 'HEALED' for e in self.events)

    def read_cache(self):
        try:
            data = json.loads(self.cache_path.read_text(encoding='utf-8'))
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}

    def save_cache(self, target, entry):
        cache = self.read_cache()
        cache[target] = entry
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        name = None
        try:
            with tempfile.NamedTemporaryFile(mode='w', dir=self.cache_path.parent,
                                              encoding='utf-8', delete=False) as stream:
                name = stream.name
                json.dump(cache, stream, ensure_ascii=False, indent=2)
            os.replace(name, self.cache_path)
        finally:
            if name and os.path.exists(name):
                os.unlink(name)

    async def resolve(self, page, target):
        """Verification must never accept a machine substitute for missing evidence."""
        self.metadata.pop(target, None)
        found = await super().resolve(page, target)
        self.remember(target, found[1], 'human')
        return found

    async def resolve_action(self, page, target):
        self.metadata.pop(target, None)
        try:
            found = await super().resolve(page, target)
            self.remember(target, found[1], 'human')
            return found
        except Blocked as original:
            if not (original.details.get('code') == 'NO_LOCATOR' or
                    original.details.get('code') == 'LOCATOR_COUNT' and original.details.get('count') == 0):
                raise
            if target not in self.targets:
                raise
            cached = self.read_cache().get(target)
            if isinstance(cached, dict):
                try:
                    # Cache entries obey the same restricted schema as proposals.
                    spec = LocatorProposal.model_validate(dict(locator=cached['locator'], rationale=cached['rationale'])).locator
                    found = await Resolver({target: spec.model_dump()}).resolve(page, target)
                    self.remember(target, found[1], 'cache')
                    return found
                except (Blocked, ValueError, KeyError):
                    pass
            if target in self.attempted:
                details = self.failures.get(target, dict(code='HEAL_FAILED', target=target, count=None, proposal=None))
                raise Blocked('heal attempt already used for target', **details) from original
            self.attempted.add(target)
            event = dict(target=target, case=self.case_id, run_id=self.run_id,
                         timestamp=datetime.now(timezone.utc).isoformat(), status='HEAL_FAILED',
                         proposal=None, count=None)
            self.events.append(event)
            try:
                snapshot = (await page.locator('body').aria_snapshot())[:SNAPSHOT_LIMIT]
                event['snapshot_hash'] = hashlib.sha256(snapshot.encode()).hexdigest()
                self.evidence_dir.mkdir(parents=True, exist_ok=True)
                snapshot_path = self.evidence_dir / ('locator-input-' + event['snapshot_hash'] + '.json')
                snapshot_path.write_text(json.dumps(dict(target=target, description=self.targets[target],
                    aria_snapshot=snapshot), ensure_ascii=False, indent=2))
                raw = await self.planner.propose(target, self.targets[target], snapshot)
                event['model'] = self.planner.model_name
                event['proposal'] = raw[:8000] if isinstance(raw, str) else raw
                proposal = LocatorProposal.model_validate_json(raw) if isinstance(raw, str) else LocatorProposal.model_validate(raw)
                event['proposal'] = proposal.model_dump()
                spec = LocatorSpec.model_validate(proposal.locator.model_dump())
                loc = self.build_locator(page, spec).filter(visible=True)
                event['count'] = await loc.count()
                if event['count'] != 1:
                    raise ValueError('Proposal must match exactly one visible element')
                cache_entry = {**event, 'status': 'HEALED', 'locator': proposal.locator.model_dump(),
                               'rationale': proposal.rationale}
                self.save_cache(target, cache_entry)
                event['status'] = 'HEALED'
                self.remember(target, spec, 'healed')
                return loc, spec
            except Exception as exc:
                # Provider exceptions may contain request content/credentials.
                event['error_type'] = type(exc).__name__
                details = dict(code='HEAL_FAILED', target=target, count=event['count'], proposal=event['proposal'])
                self.failures[target] = details
                raise Blocked('locator healing failed', **details) from None
            finally:
                self.evidence_dir.mkdir(parents=True, exist_ok=True)
                (self.evidence_dir/'locator-heals.json').write_text(json.dumps(self.events, ensure_ascii=False, indent=2))
