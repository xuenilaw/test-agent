"""Offline, escaped HTML. No model calls, scripts, or remote assets."""
import base64
import html
import io
import json
import os
import subprocess
from importlib.metadata import version
from pathlib import Path
from urllib.parse import quote

from PIL import Image

CALIBRATION_CAVEAT = ('Clef threshold 0.85 was chosen after seeing Clef\'s calibration results (post-hoc), '
    'justified by Clef\'s calibrated probabilities being on a different scale than Claude\'s self-reported confidence; '
    'replay showed 0 false PASS and 0 missed PASS on both frozen sets. Not confirmed on a new set.')
LIMITATIONS = [
    'Route geometry is a model observation, not a coordinate/topology proof.',
    'Layer tiles are not visually verified; their selected DOM state is checked.',
    'Preconditions are kept as source text, not automatically verified.',
    CALIBRATION_CAVEAT,
    'Neither provider met the full clear-mismatch FAILED acceptance bar in the measured comparison; BLOCKED needs investigation.',
]
CSS = '''body{font:15px/1.5 system-ui,sans-serif;margin:0;background:#f3f6f8;color:#182c37}
main{max-width:1200px;margin:auto;padding:28px}header{background:#173d4b;color:white;padding:26px;border-radius:12px}
.plain-summary{background:#e9f3f6;border-left:5px solid #256779;padding:16px 22px;margin:20px 0;border-radius:8px}
.plain-summary h2{margin-top:0}.badge.borderline{background:#fff0bc;color:#684500}
h1{margin:0 0 12px}h2{margin-top:32px}.metrics{display:flex;gap:16px;flex-wrap:wrap;margin:20px 0}
.metric{background:white;border:1px solid #d2dde3;border-radius:8px;padding:16px;min-width:130px}
table{border-collapse:collapse;width:100%;background:white;margin:12px 0;table-layout:auto}
th,td{border:1px solid #d2dde3;padding:10px;text-align:left;vertical-align:top;overflow-wrap:anywhere}
th{background:#e6eef1}pre{white-space:pre-wrap;overflow-wrap:anywhere;font:12px/1.5 monospace;margin:6px 0}
.badge{font-weight:700;border-radius:4px;padding:3px 7px;display:inline-block;background:#e5e9ec;white-space:nowrap}
.overview th:nth-child(1){min-width:100px}.overview th:nth-child(2){min-width:82px}
.overview th:nth-child(5){min-width:75px}.overview th:nth-child(6){min-width:130px}
.PASSED{background:#d9f1df;color:#124923}.FAILED{background:#fbdde0;color:#7b1320}.BLOCKED{background:#ffedc9;color:#684500}
details{background:white;border:1px solid #d2dde3;padding:14px;margin:14px 0;border-radius:8px}summary{cursor:pointer;font-weight:700}
img{max-width:100%;height:auto;border:1px solid #cad6db}a{color:#126176}.muted{color:#546a75}.evidence{max-width:640px}
ul{padding-left:22px}@media(max-width:700px){main{padding:12px}table{display:block;overflow-x:auto}header{padding:16px}}'''


def esc(value):
    return html.escape(str(value if value is not None else '—'),quote=True)


def short_text(value,limit):
    text=' '.join(str(value if value is not None else '—').split())
    return text if len(text)<=limit else text[:limit-1]+'…'


def locator_label(source):
    return {'human':'locator file','cache':'cache','healed':'healed (GLM)',
            'vision':'vision (Claude)'}.get(source,source)


def pretty(value):
    return '<pre>'+esc(json.dumps(value,ensure_ascii=False,indent=2,default=str))+'</pre>'


def technical(value):
    return '<details><summary>Technical details</summary>'+pretty(value)+'</details>'


def human(value):
    if value is None:return '—'
    if isinstance(value,bool):return 'Yes' if value else 'No'
    if isinstance(value,dict):return '; '.join(str(k)+': '+human(v) for k,v in value.items()) or 'none'
    if isinstance(value,list):return ', '.join(human(v) for v in value) or 'none'
    return str(value)


def seconds(value):
    return f'{value:.1f} s' if type(value) in (int,float) else '—'


def journey_time(minutes):
    if type(minutes) not in (int,float):return human(minutes)
    hours,remainder=divmod(minutes,60)
    return (f'{int(hours)} h'+(f' {remainder:g} min' if remainder else '')) if hours else f'{minutes:g} min'


def borderline(check):
    actual=check.get('actual',{});threshold=actual.get('min_confidence')
    if check.get('status')!='PASSED' or type(threshold) not in (int,float):return False
    for answer in actual.get('answers',{}).values():
        probability=answer.get('probabilities',{}).get(answer.get('choice'))
        if type(probability) in (int,float) and threshold<=probability<=threshold+.03+1e-9:return True
    return False


def check_badge(check):
    if borderline(check):return '<span class="badge borderline">PASSED (borderline)</span>'
    return badge(check.get('status'))


def vision_text(actual):
    answers=actual.get('answers',{})
    if answers:
        pieces=[]
        for question,label in [('start_city','start'),('end_city','end'),('route_line','line')]:
            answer=answers.get(question,{})
            choice=answer.get('choice','unknown');p=answer.get('probabilities',{}).get(choice)
            pieces.append(label+' '+str(choice)+(f' {p:.4f}' if type(p) in (int,float) else ''))
        return 'Clef: '+', '.join(pieces)+' (min '+human(actual.get('min_confidence'))+')'
    return human(actual.get('model_summary') or actual.get('code') or 'No model observation available')


def readable_item(item):
    actual=item.get('actual',{});expected=item.get('expected',{});kind=item.get('kind')
    if not kind:
        requested=str(item.get('action',''))+' '+str(item.get('target',''))
        if item.get('value') is not None:requested+=' → '+human(item['value'])
        return 'Requested: '+requested+' · Outcome: '+human(item.get('status'))
    operator={'less_than':'<','equals':'='}.get(expected.get('operator'),'')
    want=human(expected.get('value'))
    if kind=='duration_minutes':
        want='duration '+operator+' '+want+' min'
        got=human(actual.get('raw_text'))
        if type(actual.get('parsed_minutes')) in (int,float):got+=f" = {actual['parsed_minutes']:g} min"
    elif kind=='route_geometry':
        return 'Expected: '+human(expected.get('description') or expected.get('requirement') or 'required route')+' · '+vision_text(actual)
    elif kind=='visible':want='visible';got='visible' if actual.get('visible') else 'not confirmed visible'
    elif kind=='route_connects':got=human(actual.get('origin'))+' → '+human(actual.get('destination'))
    elif kind=='options_present':
        got=human(actual.get('options'))
        if actual.get('missing'):got+='; missing: '+human(actual['missing'])
        if actual.get('extra'):got+='; extra: '+human(actual['extra'])
    else:got=human(actual.get('value',actual.get('raw_text')))
    mark=' ✓' if item.get('status')=='PASSED' else ' ✗' if item.get('status')=='FAILED' else ''
    return 'Expected: '+want+' · Actual: '+got+mark


def operations(entry):
    heals=entry.get('heals',0);attempts=entry.get('vision_click_attempts',0)
    parts=[]
    if heals:parts.append(f'{heals} healed')
    if attempts:parts.append(f"{entry.get('vision_click_successes',0)} of {attempts} vision clicks succeeded")
    return '; '.join(parts) or '—'


def badge(status):
    css=status if status in {'PASSED','FAILED','BLOCKED','NOT_RUN'} else 'UNKNOWN'
    return '<span class="badge '+css+'">'+esc(status)+'</span>'


def read_json(path):
    try:
        data=json.loads(path.read_text())
        return data if isinstance(data,dict) else {}
    except (OSError,ValueError):
        return {}


def tool_metadata(project_root):
    meta={'version':version('test-agent'),'git_commit':None,'working_tree_dirty':None}
    try:
        meta['git_commit']=subprocess.run(['git','rev-parse','HEAD'],cwd=project_root,capture_output=True,text=True,
                                         timeout=3,check=True).stdout.strip()
        meta['working_tree_dirty']=bool(subprocess.run(['git','status','--porcelain'],cwd=project_root,
            capture_output=True,text=True,timeout=3,check=True).stdout.strip())
    except (OSError,subprocess.SubprocessError):
        pass
    return meta


class Report:
    def __init__(self,folder):
        self.folder=folder.resolve()
        self.base=next((p for p in [self.folder,*self.folder.parents] if p.name=='artifacts'),self.folder)

    def asset(self,value,context=None):
        if not isinstance(value,(str,Path)):
            return None
        path=Path(value)
        if not path.is_absolute():
            path=(context or self.folder)/path
        path=path.resolve()
        if not path.is_file():
            # Saved CI paths can refer to a different machine. Rebase only within this report.
            for index, part in enumerate(path.parts):
                if part == self.folder.name:
                    candidate=(self.folder / Path(*path.parts[index+1:])).resolve()
                    if candidate.is_relative_to(self.folder) and candidate.is_file():
                        path=candidate
                        break
        return path if path.is_relative_to(self.base) and path.is_file() else None

    def link(self,path,label):
        asset=self.asset(path)
        if not asset:
            return '<span class="muted">'+esc(label)+' unavailable</span>'
        href=quote(os.path.relpath(asset,self.folder),safe='/')
        return '<a href="'+esc(href)+'">'+esc(label)+'</a>'

    def thumbnail(self,value,context):
        path=self.asset(value,context)
        if not path:
            return '<p class="muted">Screenshot unavailable</p>'
        try:
            with Image.open(path) as original:
                image=original.convert('RGB');image.thumbnail((640,360))
                stream=io.BytesIO();image.save(stream,format='JPEG',quality=65)
            data=base64.b64encode(stream.getvalue()).decode()
        except (OSError,ValueError):
            return '<p class="muted">Screenshot unavailable</p>'
        return '<div class="evidence"><img alt="Step screenshot" src="data:image/jpeg;base64,'+data+'"><br>'+self.link(path,'Full-size screenshot')+'</div>'

    def case_data(self,entry):
        folder=entry.get('run_folder')
        if not folder:
            return None,{},{}
        result=self.asset(Path(folder)/'results.json')
        if not result:
            return None,{},{}
        return result.parent,read_json(result),read_json(result.parent/'plan.json')

    def plain_summary(self,entries,repeatability):
        groups={}
        for entry in entries:groups.setdefault(entry.get('case_id','Unknown case'),[]).append(entry)
        text='<section class="plain-summary"><h2>What happened</h2>'
        if repeatability:
            text+='<p>Same '+str(len(groups))+' cases run '+str(len(repeatability.get('runs',[])))+' times to check the results are stable.</p>'
        for case_id,group in groups.items():
            loaded=[self.case_data(entry) for entry in group]
            folder=loaded[0][0]
            source=read_json(folder/'source.json') if folder else {}
            contract=source.get('contract') or {}
            title=case_id
            if contract.get('origin') and contract.get('destination'):
                title+=' ('+str(contract['origin'])+' → '+str(contract['destination'])+')'
            statuses=list(dict.fromkeys(e.get('status','BLOCKED') for e in group))
            if len(statuses)==1:
                sentence=title+': '+statuses[0]
                if all(e.get('outcome_as_designed') is True for e in group):sentence+=' as designed'
                elif any(e.get('outcome_as_designed') is False for e in group):sentence+='; not as designed'
                sentence+='.'
            else:
                sentence=title+': results varied — '+', '.join(f"Run {i+1} {e.get('status','BLOCKED')}" for i,e in enumerate(group))+'.'
            durations=[(s.get('source_step'),c) for _,result,_ in loaded for s in result.get('steps',[])
                       for c in s.get('checks',[]) if c.get('kind')=='duration_minutes']
            if durations:
                step,check=durations[0];minutes=check.get('actual',{}).get('parsed_minutes');limit=check.get('expected',{}).get('value')
                values=[c.get('actual',{}).get('parsed_minutes') for _,c in durations]
                if type(minutes) in (int,float) and type(limit) in (int,float) and all(v==minutes for v in values):
                    sentence+=f' Step {step} duration {journey_time(minutes)} is '+('not ' if minutes>=limit else '')+'under '+journey_time(limit)+'.'
                else:sentence+=' Duration results differ or are unavailable; see the step details.'
            elif contract.get('selected_layer'):
                sentence+=' Requested layer: '+str(contract['selected_layer'])+'.'
            elif group[0].get('reason'):
                sentence+=' '+str(group[0]['reason'])
            visuals=[c for _,result,_ in loaded for step in result.get('steps',[]) for c in step.get('checks',[]) if c.get('kind')=='route_geometry']
            if visuals:
                visual_statuses={c.get('status') for c in visuals}
                provider=str(visuals[0].get('actual',{}).get('provider') or 'Vision model').capitalize()
                description=('unsure (UNCLEAR)' if visual_statuses=={'BLOCKED'} else
                    'confirmed'+(' (borderline)' if any(borderline(c) for c in visuals) else '') if visual_statuses=={'PASSED'} else
                    'route mismatch' if visual_statuses=={'FAILED'} else
                    'not checked (NOT_RUN)' if visual_statuses=={'NOT_RUN'} else 'results varied; see each run')
                sentence+=' Route picture: '+provider+' '+description+'.'
            text+='<p>'+esc(sentence)+'</p>'
        return text+'</section>'

    def repeat_case(self,case):
        text='<details><summary>'+esc(case['case_id'])+' · probability spread and differences</summary>'
        text+='<p>Reasons by run: '+esc('; '.join(f'Run {i+1}: '+human(r) for i,r in enumerate(case.get('reasons',[]))))+'</p>'
        for check in case.get('vision_checks',[]):
            text+='<p>Upstream providers: '+esc(human(check.get('upstream_providers_seen')))+' · Hosts: '+esc(human(check.get('upstream_hosts_seen')))+'</p>'
            text+='<table><tr><th>Question</th><th>Chosen options</th><th>Selected probability min / max</th></tr>'
            for question,spread in check.get('probability_spread',{}).items():
                bounds=spread['chosen_probability']
                interval=' / '.join(f'{bounds[k]:.4f}' if type(bounds.get(k)) in (int,float) else '—' for k in ['min','max'])
                text+='<tr><td>'+esc(question)+'</td><td>'+esc(human(list(dict.fromkeys(spread.get('choices',[])))))+'</td><td>'+esc(interval)+'</td></tr>'
            text+='</table>'
        for difference in case.get('differences',[]):
            text+='<p>Step '+esc(difference['step'])+' differs:</p><ul>'+''.join('<li>Run '+esc(r['run'])+': '+esc(r['status'])+' — '+esc(r.get('reason'))+'</li>' for r in difference['runs'])+'</ul>'
        return text+technical(case)+'</details>'

    def case(self,entry,index):
        folder,data,plan=self.case_data(entry)
        text='<details id="case-'+str(index)+'"><summary>'+esc(entry.get('run_label',''))+' '+esc(entry.get('case_id'))+' '+badge(entry.get('status'))+'</summary>'
        text+='<p>'+esc(entry.get('reason'))+'</p>'
        if not folder:
            return text+technical(entry)+'</details>'
        source=read_json(folder/'source.json').get('case',{})
        text+='<p><strong>Name:</strong> '+esc(source.get('name',source.get('case_name',entry.get('case_id'))))+'</p>'
        text+='<p><strong>Preconditions (text):</strong> '+esc(plan.get('preconditions'))+'</p>'
        steps={s.get('source_step'):s for s in plan.get('steps',[])}
        for step in data.get('steps',[]):
            original=steps.get(step.get('source_step'),{})
            status=step.get('status')
            label=badge(status)
            borderline_check=next((c for c in step.get('checks',[]) if borderline(c)),None)
            if status=='PASSED' and borderline_check:
                label=check_badge(borderline_check)
            text+='<details class="step"><summary>Step '+esc(step.get('source_step'))+' – '+esc(short_text(original.get('source_action'),100))+' '+label
            if status!='PASSED' and step.get('reason'):
                text+=' · '+esc(short_text(step['reason'],120))
            text+='</summary>'
            text+='<table><tr><th>Source action</th><th>Expected result</th><th>Reason</th></tr><tr><td>'+esc(original.get('source_action'))+'</td><td>'+esc(original.get('source_expected'))+'</td><td>'+esc(step.get('reason'))+'</td></tr></table>'
            text+='<table><tr><th>Action / check</th><th>Status</th><th>Locator source</th><th>Expected / actual / reason</th></tr>'
            for kind,items in [('Action',step.get('actions',[])),('Check',step.get('checks',[]))]:
                for item in items:
                    status=check_badge(item) if kind=='Check' else badge(item.get('status'))
                    details='<p>'+esc(readable_item(item))+'</p>'
                    if item.get('reason'):details+='<p>Reason: '+esc(item['reason'])+'</p>'
                    text+='<tr><td>'+esc(kind+' '+str(item.get('action',item.get('kind','')))+' · '+str(item.get('target','')))+'</td><td>'+status+'</td><td>'+esc(locator_label(item.get('locator_source')))+'</td><td>'+details+technical(item)+'</td></tr>'
            text+='</table><p class="muted">Locator source: locator file = configured locator; cache = saved locator; healed (GLM) = recovered DOM locator; vision (Claude) = screenshot click.</p>'+self.thumbnail(step.get('screenshot'),folder)
            for check in step.get('checks',[]):
                if check.get('kind')=='route_geometry':
                    actual=check.get('actual',{})
                    text+='<h4>Vision evidence</h4><p>'+esc(vision_text(actual))+'</p>'
            text+='</details>'
        cleanup=data.get('cleanup',[])
        cleanup_status='PASSED' if cleanup and all(item.get('status')=='PASSED' for item in cleanup) else 'NOT_RUN'
        for status in ['FAILED','BLOCKED','NOT_RUN']:
            if any(item.get('status')==status for item in cleanup):
                cleanup_status=status
                break
        text+='<details class="cleanup"><summary>Cleanup – '+str(len(cleanup))+' actions '+badge(cleanup_status)+'</summary><ul>'+''.join('<li>'+badge(item.get('status'))+' '+esc(readable_item(item))+(' · '+esc(item['reason']) if item.get('reason') else '')+'</li>' for item in cleanup)+'</ul>'+technical(cleanup)+'</details>'
        text+='<p>'+self.link(folder/'results.json','results.json')+' · '+self.link(folder/'trace.zip','trace.zip')+'</p></details>'
        return text

    def write(self,summary,repeatability=None):
        entries=summary.get('cases',[])
        observed=[]
        vision_counts={s:0 for s in ['PASSED','FAILED','BLOCKED','NOT_RUN']}
        for entry in entries:
            _,data,_=self.case_data(entry)
            for step in data.get('steps',[]):
                for check in step.get('checks',[]):
                    if check.get('kind')=='route_geometry':
                        status=check.get('status','NOT_RUN')
                        if status in vision_counts:vision_counts[status]+=1
                        actual=check.get('actual',{})
                        row={k:actual.get(k,'not reported') for k in ['provider','model','api_host','upstream_host','upstream_provider','min_confidence']}
                        if row not in observed:observed.append(row)
                for action in step.get('actions',[]):
                    if action.get('locator_source')=='vision':
                        row={k:action.get(k,'not reported') for k in ['provider','model','api_host','upstream_host','upstream_provider','min_confidence']}
                        row['operation']='vision click'
                        if row not in observed:observed.append(row)
        text='<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta http-equiv="Content-Security-Policy" content="default-src &#39;none&#39;; img-src data:; style-src &#39;unsafe-inline&#39;; base-uri &#39;none&#39;"><title>Test Agent report</title><style>'+CSS+'</style></head><body><main>'
        tool=summary.get('tool') or {}
        text+='<header><h1>Test Agent · '+('Repeatability' if repeatability else 'Suite report')+'</h1><p>Date/time: '+esc(summary.get('started_at'))+'</p><p>Workbook: '+esc(summary.get('workbook'))+'</p><p>Faults: '+esc(human(summary.get('faults_injected',[])))+'</p><p>Tool: '+esc(tool.get('version'))+' · Git '+esc(tool.get('git_commit'))+' · working tree dirty: '+esc(human(tool.get('working_tree_dirty')))+'</p></header>'
        if repeatability:
            count=len(repeatability.get('runs',[]));cases=len({e.get('case_id') for e in entries})
            text+=f'<p>This repeat report contains {count} suite runs × {cases} cases. Each suite report shows one run:</p><ul>'+''.join('<li>'+self.link(Path(run['output_directory'])/'report.html','Run '+str(i+1)+' report')+'</li>' for i,run in enumerate(repeatability.get('runs',[])))+'</ul>'
        else:
            text+='<p>This suite report contains one run of '+str(len(entries))+' cases.</p>'
        text+=self.plain_summary(entries,repeatability)
        text+='<h2>Vision provider / model / threshold used</h2>'
        if observed:
            text+='<table><tr>'+''.join('<th>'+esc(h)+'</th>' for h in ['Provider / operation','Model','Threshold','API host','Upstream provider','Upstream host (if reported)'])+'</tr>'
            for row in observed:
                values=[str(row.get('provider'))+' / '+row.get('operation','route'),row.get('model'),row.get('min_confidence'),row.get('api_host'),row.get('upstream_provider'),row.get('upstream_host')]
                text+='<tr>'+''.join('<td>'+esc(v)+'</td>' for v in values)+'</tr>'
            text+='</table>'
        else:
            text+='<p>'+esc(human(summary.get('vision_configuration','No route vision executed')))+'</p>'
        text+='<p>Route vision checks (separate from case verdicts): '+esc(' · '.join(f'{s}: {n}' for s,n in vision_counts.items()))+'</p>'
        if (self.folder/'audit_analysis.md').is_file():
            text+='<p>'+self.link(self.folder/'audit_analysis.md','AI audit analysis — suggestion, verify before acting')+'</p>'
            analysis=read_json(self.folder/'audit_analysis.json')
            from test_agent.audit_presentation import html_audit
            text+=html_audit(analysis)
        text+='<h2>Case totals</h2><div class="metrics">'+''.join('<div class="metric">'+badge(status)+'<br><strong>'+esc(summary.get('totals',{}).get(status,0))+'</strong></div>' for status in ['PASSED','FAILED','BLOCKED'])+'</div>'
        if summary.get('reason'):text+='<p>'+esc(summary['reason'])+'</p>'
        if repeatability:
            text+='<h2>Repeatability</h2><table><tr><th>Case</th><th>Statuses by run</th><th>Consistent status?</th><th>Duration mean / min / max (s)</th></tr>'
            for case in repeatability.get('cases',[]):
                duration=' / '.join(seconds(case['durations'][key]) for key in ['mean','min','max'])
                text+='<tr><td>'+esc(case['case_id'])+'</td><td>'+' '.join(badge(s) for s in case['statuses'])+'</td><td>'+esc(human(case['consistent']))+'</td><td>'+esc(duration)+'</td></tr>'
            text+='</table>'
            for case in repeatability.get('cases',[]):
                text+=self.repeat_case(case)
        text+='<h2>Case overview</h2><table class="overview"><tr><th>Case</th><th>Status</th><th>Designed / as designed</th><th>Reason</th><th>Duration s</th><th>Heals / vision clicks</th></tr>'
        for i,entry in enumerate(entries):
            text+='<tr><td><a href="#case-'+str(i)+'">'+esc(entry.get('run_label',''))+' '+esc(entry.get('case_id'))+'</a></td><td>'+badge(entry.get('status'))+'</td><td>'+esc(entry.get('designed_outcome'))+' / '+esc(human(entry.get('outcome_as_designed')))+'</td><td>'+esc(entry.get('reason'))+'</td><td>'+esc(seconds(entry.get('duration_seconds')))+'</td><td>'+esc(operations(entry))+'</td></tr>'
        text+='</table>'+''.join(self.case(entry,i) for i,entry in enumerate(entries))
        text+='<h2>Known limitations</h2><ul>'+''.join('<li>'+esc(item)+'</li>' for item in LIMITATIONS)+'</ul></main></body></html>'
        path=self.folder/'report.html';path.write_text(text,encoding='utf-8')
        return path


def build_report(folder):
    repeat=read_json(folder/'repeatability.json')
    if repeat:
        return Report(folder).write(repeat['summary'],repeat)
    summary=read_json(folder/'summary.json')
    if not summary:
        raise ValueError('No suite summary.json or repeatability.json')
    return Report(folder).write(summary)
