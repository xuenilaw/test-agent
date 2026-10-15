"""Offline arithmetic over saved reports; never calls a model or changes a label."""
import json
from collections import defaultdict

from test_agent.verification.calibration import summarize

PRICING_SOURCE='https://platform.claude.com/docs/en/about-claude/pricing'


def cost(record):
    usage=record.get('usage',{})
    if 'cost' in usage:
        return usage['cost'],'reported'
    # Verified 2026-10-15, short prompts, standard API (no batch/service-tier modifiers).
    if record.get('model')=='claude-haiku-5-5' and usage and usage.get('input_tokens',0)<=100_000:
        value=(usage.get('input_tokens',0)*.10+usage.get('output_tokens',0)*.50+
               usage.get('cache_creation_input_tokens',0)*.125+usage.get('cache_read_input_tokens',0)*.01)/1_000_000
        return value,'estimated'
    return None,'unknown'


def compare(groups):
    result={}
    jpeg_hashes=None
    for name,paths in groups.items():
        records=[]
        for path in paths:
            report=json.loads((path/'results.json').read_text())
            if report['min_confidence']!=.90:
                raise ValueError('Comparison requires 0.90 reports')
            records.extend(report['records'])
        summary=summarize(records)
        sent=[(r['image'],r.get('sha256')) for r in records if r.get('image_variant')=='jpeg']
        if sent:
            if not all(sha for _,sha in sent):
                raise ValueError('Missing JPEG byte hash')
            if jpeg_hashes is None:
                jpeg_hashes=sent
            elif sent!=jpeg_hashes:
                raise ValueError('Compared JPEG bytes differ')
        costs=[cost(r) for r in records]
        summary['cost']=dict(mean_usd_per_call=(sum(c for c,_ in costs)/len(costs) if all(c is not None for c,_ in costs) else None),
            reported_calls=sum(b=='reported' for _,b in costs),estimated_calls=sum(b=='estimated' for _,b in costs),
            unknown_calls=sum(b=='unknown' for _,b in costs),pricing_source=PRICING_SOURCE,pricing_checked='2026-10-15')
        per_image=defaultdict(list)
        for record in records:
            if record.get('answers'):
                per_image[record['image']].append(json.dumps(record['answers'],sort_keys=True))
        summary['unique_answer_vectors']={image:len(set(values)) for image,values in per_image.items()}
        summary['source_reports']=[str(p) for p in paths]
        result[name]=summary
    first=None
    for paths in groups.values():
        signatures=[]
        for path in paths:
            signatures.extend((r['image'],r['attempt'],r['expected'],r['ideal'],r['requirement'])
                              for r in json.loads((path/'results.json').read_text())['records'])
        if first is None:
            first=signatures
        elif signatures!=first:
            raise ValueError('Comparison labels/attempts/requirements differ')
    return result


def markdown(comparison):
    lines=['# Frozen-image comparison at 0.90','',
        '| Metric | '+' | '.join(comparison)+' |','|---|'+'---:|'*len(comparison)]
    metrics={
        'Calls':lambda s:str(s['totals']['calls']),
        'False PASS':lambda s:str(s['totals']['false_pass']),
        'Correct-image PASS':lambda s:f"{s['totals']['correct_pass_rate']:.1%}",
        'Clear-mismatch FAILED':lambda s:f"{s['totals']['correct_failed_rate']:.1%}",
        'BLOCKED':lambda s:f"{s['totals']['blocked_rate']:.1%}",
        'Codes':lambda s:str(s['totals']['error_codes']),
        'Latency p50 / p95 ms':lambda s:f"{s['performance']['latency_p50_ms']:.1f} / {s['performance']['latency_p95_ms']:.1f}",
        'USD/call (reported or estimated below)':lambda s:(f"{s['cost']['mean_usd_per_call']:.8f}" if s['cost']['mean_usd_per_call'] is not None else 'unknown'),
        'Acceptance (all criteria)':lambda s:str(s['totals']['ready_for_clef']),
    }
    for metric,formatter in metrics.items():
        lines.append('| '+metric+' | '+' | '.join(formatter(s) for s in comparison.values())+' |')
    lines+=['', 'Cost basis:']
    for name,summary in comparison.items():
        c=summary['cost']
        lines.append(f"- {name}: {c['reported_calls']} reported / {c['estimated_calls']} estimated / {c['unknown_calls']} unknown calls.")
    lines+=['',f'Claude estimates use published short-prompt standard rates checked 2026-10-15: {PRICING_SOURCE}. Not an invoice.',
        'Acceptance: zero false PASS; correct-image PASS ≥90%; clear-mismatch FAILED ≥80%; no internal errors.',
        'Repeated sample at fixed settings; no prompt, compression, threshold or label tuning after observing these results.']
    return '\n'.join(lines)+'\n'
