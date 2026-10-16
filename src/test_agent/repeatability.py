"""Repeated execution with validated plans; no translation inside the measurement."""
import json
import statistics
from datetime import datetime,timezone
from pathlib import Path

from test_agent.plan_loader import load_plan
from test_agent.readers.excel import read_case_ids
from test_agent.reporting import build_report,read_json,tool_metadata
from test_agent.suite import reusable_plan,run_suite


def bounds(values):
    return dict(min=min(values),max=max(values)) if values else dict(min=None,max=None)


def summarize_repeats(runs):
    cases=[]
    ids=list(dict.fromkeys(c['case_id'] for run in runs for c in run['cases']))
    for case_id in ids:
        entries=[next((c for c in run['cases'] if c['case_id']==case_id),{}) for run in runs]
        statuses=[e.get('status','BLOCKED') for e in entries]
        results=[read_json(Path(e['run_folder'])/'results.json') if e.get('run_folder') else {} for e in entries]
        durations=[e.get('execution_seconds',e.get('duration_seconds',0)) for e in entries]
        differences=[]
        step_ids=sorted({s['source_step'] for result in results for s in result.get('steps',[])})
        for step in step_ids:
            observations=[next((s for s in r.get('steps',[]) if s['source_step']==step),{}) for r in results]
            signatures=[(s.get('status','NOT_RUN'),s.get('reason')) for s in observations]
            if len(set(signatures))>1:
                differences.append(dict(step=step,runs=[dict(run=i+1,status=s[0],reason=s[1]) for i,s in enumerate(signatures)]))
        checks={}
        for index,result in enumerate(results):
            for step in result.get('steps',[]):
                for ci,check in enumerate(step.get('checks',[])):
                    if check.get('kind')!='route_geometry':continue
                    key=f"{step['source_step']}:{ci}"
                    checks.setdefault(key,[]).append(dict(run=index+1,**check.get('actual',{})))
        vision=[]
        for key,records in checks.items():
            spread={}
            questions=list(dict.fromkeys(q for r in records for q in r.get('answers',{})))
            for question in questions:
                answers=[r['answers'][question] for r in records if question in r.get('answers',{})]
                options={option:bounds([a['probabilities'][option] for a in answers if option in a['probabilities']])
                         for option in dict.fromkeys(o for a in answers for o in a['probabilities'])}
                spread[question]=dict(options=options,chosen_probability=bounds([a['probabilities'][a['choice']] for a in answers]),
                    confidence=bounds([a['confidence'] for a in answers]),choices=[a['choice'] for a in answers])
            vision.append(dict(check=key,observed_runs=[r['run'] for r in records],probability_spread=spread,
                providers=sorted({r['provider'] for r in records if r.get('provider')}),
                models=sorted({r['model'] for r in records if r.get('model')}),
                thresholds=sorted({r['min_confidence'] for r in records if isinstance(r.get('min_confidence'),(int,float))}),
                upstream_hosts_seen=sorted({r['upstream_host'] for r in records if r.get('upstream_host')}),
                upstream_providers_seen=sorted({r['upstream_provider'] for r in records if r.get('upstream_provider')}),
                api_hosts_seen=sorted({r['api_host'] for r in records if r.get('api_host')})))
        cases.append(dict(case_id=case_id,statuses=statuses,consistent=len(set(statuses))==1,
            durations=dict(mean=statistics.mean(durations),**bounds(durations)),differences=differences,
            reasons=[e.get('reason') for e in entries],vision_checks=vision))
    return cases


async def run_repeat(workbook,locators,project_root,*,times=3,headed=False,output_root=None):
    if type(times) is not int or not 1<=times<=100:
        raise ValueError('times must be an integer from 1 to 100')
    # Fail before the first browser if any current plan is absent. Never call GLM.
    for case_id in read_case_ids(workbook):
        folder=reusable_plan(project_root/'artifacts',workbook,case_id,'https://www.openstreetmap.org/')
        if folder is None:
            raise ValueError('repeat requires a current VALIDATED plan for '+case_id+'; translate or revalidate first')
        load_plan(folder)
    started=datetime.now(timezone.utc)
    output=(output_root or project_root/'artifacts')/('repeat-'+started.strftime('%Y%m%dT%H%M%S%fZ'))
    output.mkdir(parents=True)
    report=dict(started_at=started.isoformat(),times=times,runs=[],cases=[])
    for index in range(times):
        print(f'Repeat {index+1}/{times}',flush=True)
        result=await run_suite(workbook,locators,project_root,reuse=True,require_reuse=True,headed=headed,
                               output_root=output,plan_root=project_root/'artifacts',output_folder=output/f'run-{index+1}')
        report['runs'].append(result)
        report['cases']=summarize_repeats(report['runs'])
        entries=[dict(entry,run_label=f'Run {i+1}') for i,run in enumerate(report['runs']) for entry in run['cases']]
        statuses=[e['status'] for e in entries]
        report['summary']=dict(started_at=started.isoformat(),workbook=str(workbook.resolve()),
            tool=tool_metadata(project_root),cases=entries,faults_injected=[],reason=None,
            status='FAILED' if 'FAILED' in statuses else 'BLOCKED' if 'BLOCKED' in statuses else 'PASSED',
            totals={s:statuses.count(s) for s in ['PASSED','FAILED','BLOCKED']})
        report['output_directory']=str(output.resolve())
        (output/'repeatability.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
        build_report(output)
        from test_agent.audit import build_audit
        build_audit(output)
        from test_agent.junit import build_junit
        build_junit(output)
    return report
