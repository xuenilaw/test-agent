"""Frozen-image calibration; model calls and pure threshold replay never open OSM."""
import json
import math
import statistics
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal
from pydantic import Field, model_validator
from test_agent.schemas.plan import StrictModel
from test_agent.schemas.contracts import NonblankText, RouteContract,threshold_for
from test_agent.verification.vision import VisualObservation, ClefObservation, decide, verify_route_image


class Requirement(StrictModel):
    origin: NonblankText
    destination: NonblankText


class Label(StrictModel):
    file: NonblankText
    route_shown: NonblankText
    requirement: Requirement
    expected: Literal['PASS', 'NOT_PASS']
    ideal: Literal['PASSED', 'FAILED', 'BLOCKED']
    why: NonblankText

    @model_validator(mode='after')
    def check(self):
        if Path(self.file).name != self.file or not self.file.endswith('.png'):
            raise ValueError('Label file must be a PNG basename')
        if (self.expected == 'PASS') != (self.ideal == 'PASSED'):
            raise ValueError('Expected and ideal labels disagree')
        return self


def load_labels(folder):
    raw = json.loads((folder / 'labels.json').read_text(encoding='utf-8'))
    if not isinstance(raw, list) or not raw:
        raise ValueError('labels.json must be a nonempty list')
    labels = [Label.model_validate(item) for item in raw]
    names = [item.file for item in labels]
    if len(set(names)) != len(names):
        raise ValueError('Duplicate image label')
    for item in labels:
        image = folder / 'images' / item.file
        if not image.is_file() or not image.resolve().is_relative_to((folder / 'images').resolve()):
            raise ValueError('Unknown image file: ' + item.file)
        if not image.read_bytes().startswith(b'\x89PNG\r\n\x1a\n'):
            raise ValueError('Invalid PNG: ' + item.file)
    if set(names) != {p.name for p in (folder / 'images').glob('*.png')}:
        raise ValueError('Every PNG must have exactly one label')
    return labels


def percentile(values, fraction):
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered)-1) * fraction
    low, high = math.floor(position), math.ceil(position)
    return ordered[low] + (ordered[high]-ordered[low]) * (position-low)


def totals(records):
    positives = [r for r in records if r['expected'] == 'PASS']
    negatives = [r for r in records if r['expected'] == 'NOT_PASS']
    clear = [r for r in records if r['ideal'] == 'FAILED']
    false = sum(r['status'] == 'PASSED' for r in negatives)
    missed = sum(r['status'] != 'PASSED' for r in positives)
    failed = sum(r['status'] == 'FAILED' for r in clear)
    codes = dict(Counter(r['code'] for r in records if r.get('code')))
    correct_rate = (len(positives)-missed)/len(positives) if positives else 0
    failed_rate = failed/len(clear) if clear else 0
    acceptance = dict(false_pass_zero=false == 0, correct_pass_at_least_90_percent=correct_rate >= .9,
                      clear_mismatch_failed_at_least_80_percent=failed_rate >= .8,
                      no_internal_errors=not codes.get('VISION_INTERNAL', 0))
    return dict(calls=len(records), false_pass=false, missed_pass=missed,
                positive_calls=len(positives), clear_mismatch_calls=len(clear),
                correct_pass_rate=correct_rate, correct_failed_rate=failed_rate,
                blocked_rate=sum(r['status']=='BLOCKED' for r in records)/len(records) if records else 0,
                error_codes=codes, acceptance=acceptance, ready_for_clef=all(acceptance.values()))


def rescore(records, threshold):
    replay = []
    for record in records:
        item = dict(record)
        if record.get('observation') and record.get('code') in (None, 'VISION_INCONCLUSIVE', 'VISION_RULE_REJECTED'):
            item['status'], item['reason'], item['code'] = decide(
                (ClefObservation if record.get('observation_schema')=='clef-blind-v1' else VisualObservation).model_validate(record['observation']), record['requirement'], threshold)
        replay.append(item)
    return totals(replay)


def summarize(records):
    per_image = {}
    for name in dict.fromkeys(r['image'] for r in records):
        group = [r for r in records if r['image']==name]
        confidences = [(ClefObservation.model_validate(r['observation']).confidence if
            r.get('observation_schema')=='clef-blind-v1' else r['observation']['confidence']) for r in group if r.get('observation')]
        summaries = Counter(r['model_summary'] for r in group if r.get('model_summary'))
        per_image[name] = dict(counts={s:sum(r['status']==s for r in group) for s in ('PASSED','FAILED','BLOCKED')},
            confidence_min=min(confidences) if confidences else None,
            confidence_median=statistics.median(confidences) if confidences else None,
            confidence_max=max(confidences) if confidences else None,
            most_common_summary=summaries.most_common(1)[0][0] if summaries else None)
    latency = [r['latency_ms'] for r in records]
    reported = [r for r in records if r.get('usage')]
    performance = dict(latency_p50_ms=percentile(latency,.5), latency_p95_ms=percentile(latency,.95),
        mean_input_tokens_per_attempt=sum(r.get('usage',{}).get('input_tokens',r.get('usage',{}).get('prompt_tokens',0)) for r in records)/len(records),
        mean_output_tokens_per_attempt=sum(r.get('usage',{}).get('output_tokens',r.get('usage',{}).get('completion_tokens',0)) for r in records)/len(records),
        usage_reported_calls=len(reported), served_models=sorted({r['model'] for r in records if r.get('model')}))
    return dict(totals=totals(records), per_image=per_image, performance=performance,
                thresholds={str(t):rescore(records,t) for t in (.80,.85,.90,.95)})


def report_markdown(summary, threshold):
    t = summary['totals']; p=summary['performance']
    lines = [f'# Vision calibration at {threshold}', '',
        f"Calls: {t['calls']} | false PASS: {t['false_pass']} | missed PASS: {t['missed_pass']}",
        f"Correct image PASS: {t['correct_pass_rate']:.1%} | clear mismatch FAILED: {t['correct_failed_rate']:.1%} | BLOCKED: {t['blocked_rate']:.1%}",
        f"Error codes: {t['error_codes']}",
        f"Latency p50/p95 (ms): {p['latency_p50_ms']:.1f} / {p['latency_p95_ms']:.1f}",
        f"Mean input/output tokens per attempt: {p['mean_input_tokens_per_attempt']:.1f} / {p['mean_output_tokens_per_attempt']:.1f}",
        f"Usage reported: {p['usage_reported_calls']}/{t['calls']}; missing usage contributes zero (a lower bound, not an exact bill).",
        f"Served models: {p['served_models']}", '',
        '| Image | PASSED | FAILED | BLOCKED | Confidence min/median/max | Most common model summary |',
        '| --- | ---: | ---: | ---: | --- | --- |']
    for name,g in summary['per_image'].items():
        c=g['counts']; confidence='/'.join(str(g[k]) for k in ('confidence_min','confidence_median','confidence_max'))
        text=(g['most_common_summary'] or 'No model explanation').replace('|','\\|').replace('\n',' ')
        lines.append(f"| {name} | {c['PASSED']} | {c['FAILED']} | {c['BLOCKED']} | {confidence} | {text} |")
    lines += ['', '| Threshold (same observations) | False PASS | Missed PASS |', '| --- | ---: | ---: |']
    for threshold,result in summary['thresholds'].items():
        lines.append(f"| {threshold} | {result['false_pass']} | {result['missed_pass']} |")
    lines += ['', 'Acceptance:'] + [f"- {key}: {'PASS' if passed else 'FAIL'}" for key,passed in t['acceptance'].items()]
    lines += ['', f"Ready for Clef comparison: {t['ready_for_clef']}", '',
        'Small fixed sample; model confidence is self-reported. Frozen tiles are not all future OSM appearances.',
        'Model summaries are untrusted explanations, not proof. No prompt/label tuning or retries.']
    return '\n'.join(lines)+'\n'


async def run_calibration(folder: Path, *, provider, contract: dict, project_root: Path, runs=5, output_root=None, image_variant='png'):
    if isinstance(runs,bool) or not isinstance(runs,int) or not 1 <= runs <= 100:
        raise ValueError('runs must be an integer from 1 to 100')
    labels = load_labels(folder)
    if image_variant not in {'png','jpeg'}:
        raise ValueError('Unknown image variant')
    if image_variant=='jpeg':
        from test_agent.verification.compression import frozen_image
        for label in labels:
            frozen_image(folder,label)  # Validate all frozen inputs before any model call.
    typed = RouteContract.model_validate(contract)
    definitions = [v.model_dump() for v in typed.vision_checks if v.kind=='route_geometry']
    if len(definitions)!=1:
        raise ValueError('Calibration requires exactly one route_geometry contract declaration')
    definition={**definitions[0],'min_confidence':threshold_for(definitions[0],getattr(provider,'provider_name',None))}
    if any(label.requirement.model_dump()!=dict(origin=typed.origin,destination=typed.destination) for label in labels):
        raise ValueError('Calibration labels must match the current contract endpoints')
    stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    output=(output_root or project_root / 'artifacts') / ('calibration-'+stamp)
    output.mkdir(parents=True)
    (output / 'labels.json').write_text(json.dumps([l.model_dump() for l in labels],indent=2))
    (output / 'contract.json').write_text(typed.model_dump_json(indent=2))
    records=[]
    for label in labels:
        for attempt in range(1,runs+1):
            started=time.perf_counter()
            image,metadata=(frozen_image(folder,label) if image_variant=='jpeg' else (folder/'images'/label.file,None))
            checked=await verify_route_image(image,contract,provider,
                output / 'responses' / Path(label.file).stem / str(attempt),definition=definition,image_metadata=metadata)
            a=checked.actual
            records.append(dict(image=label.file,attempt=attempt,expected=label.expected,ideal=label.ideal,
                requirement=label.requirement.model_dump(),status=checked.status,reason=checked.reason,
                code=a.get('code'),model_summary=a.get('model_summary'),observation=a.get('observation'),
                observation_schema=a.get('observation_schema'),image_variant=image_variant,
                answers=a.get('answers'),image_preprocessing=a.get('image_preprocessing'),
                sha256=a.get('sha256'),model=a.get('model'),usage=a.get('usage',{}),
                latency_ms=a.get('latency_ms',round((time.perf_counter()-started)*1000))))
            (output / 'results.json').write_text(json.dumps(dict(records=records,min_confidence=definition['min_confidence']),indent=2))
            print(f"{label.file} {attempt}/{runs}: {checked.status}",flush=True)
    summary=summarize(records)
    (output / 'results.json').write_text(json.dumps(dict(records=records,summary=summary,
        min_confidence=definition['min_confidence']),indent=2))
    report=report_markdown(summary,definition['min_confidence'])
    (output / 'report.md').write_text(report,encoding='utf-8')
    return output,report
