"""Outer case loop: one case failure never hides later cases."""
import argparse
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from test_agent.readers.excel import read_case_ids
from test_agent.plan_loader import load_plan
from test_agent.runner import run_case
from test_agent.schemas.contracts import parse_contract
from test_agent.faults import validate_fault_names, validate_fault_targets, applicable_faults, FaultInputError
from test_agent.reporting import build_report,tool_metadata


def reusable_plan(root: Path, workbook: Path, case_id: str, url: str):
    candidates=list(root.glob(f'**/translation-*/cases/{case_id}/validation.json'))
    for report in sorted(candidates,key=lambda p:p.stat().st_mtime_ns,reverse=True):
        try:
            _,source=load_plan(report.parent)
            if Path(source['case']['source']['file']).resolve()!=workbook.resolve() or source['application_url']!=url:
                continue
            if Path(source.get('contract_file',workbook.parent/'contracts.json')).resolve()!=(workbook.parent/'contracts.json').resolve():
                continue
            if Path(source.get('vocabulary_file',workbook.parent/'vocabulary.json')).resolve()!=(workbook.parent/'vocabulary.json').resolve():
                continue
            if (workbook.parent/'vocabulary.json').exists() and not source.get('vocabulary'):
                continue
            return report.parent
        except (ValueError,OSError,KeyError):
            continue
    return None


async def run_suite(workbook: Path, locators: Path, project_root: Path, *, reuse=False,
                    skip_vision=False, headed=False, output_root=None, url='https://www.openstreetmap.org/', faults=None,require_reuse=False,plan_root=None):
    from test_agent.cli import run_translation
    faults = list(dict.fromkeys(faults or []))
    validate_fault_names(faults)
    start=time.perf_counter()
    stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    artifact_root=output_root or project_root/'artifacts'
    output=artifact_root/('suite-'+stamp); output.mkdir(parents=True)
    from dotenv import load_dotenv
    load_dotenv(project_root/'.env')
    summary=dict(workbook=str(workbook.resolve()),output_directory=str(output.resolve()),cases=[],status='BLOCKED',reason=None,faults_injected=faults,
        started_at=datetime.now(timezone.utc).isoformat(),tool=tool_metadata(project_root),
        vision_configuration=dict(provider=os.getenv('VISION_PROVIDER','clef'),model=os.getenv('VISION_MODEL'),executed=False))
    async def execute(entry,folder,selected_faults):
        case_id=entry['case_id']
        print(f"{case_id}: running"+(' (reused plan)' if entry['reused'] else '')+'...',flush=True)
        started=time.perf_counter()
        try:
            result=await run_case(folder,locators,project_root,output_root=output,headed=headed,
                                  skip_vision=skip_vision,faults=selected_faults)
            entry.update(status=result.status,reason=result.reason,run_folder=result.output_directory,
                heals=getattr(result,'locator_heals',0),vision_click_attempts=getattr(result,'vision_click_attempts',0),
                vision_click_successes=getattr(result,'vision_click_successes',0))
            entry['fault_outcomes_as_designed']=getattr(result,'fault_outcomes_as_designed',{})
            entry['outcome_as_designed']=(result.outcome_as_designed if selected_faults else
                result.status==entry['designed_outcome'] if entry['designed_outcome'] else None)
        except Exception as exc:
            entry['reason']=str(exc) if isinstance(exc,ValueError) else type(exc).__name__
        finally:
            entry['execution_seconds']=round(time.perf_counter()-started,3)
            (output/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2))
    try:
        case_ids=read_case_ids(workbook)
        path=workbook.parent/'contracts.json'
        contracts=json.loads(path.read_text()) if path.exists() else {}
        if not isinstance(contracts,dict):
            raise ValueError('Contracts must be an object')
        prepared=[]
        for case_id in case_ids:
            case_start=time.perf_counter()
            entry=dict(case_id=case_id,status='BLOCKED',reason=None,translation_folder=None,run_folder=None,
                       translation_seconds=0,execution_seconds=0,reused=False,heals=0,faults_injected=[],designed_outcome=None,outcome_as_designed=None)
            summary['cases'].append(entry)
            try:
                contract=parse_contract(contracts[case_id]).model_dump() if case_id in contracts else None
                entry['designed_outcome']=(contract or {}).get('designed_outcome')
                folder=reusable_plan(plan_root or artifact_root,workbook,case_id,url) if reuse else None
                entry['reused']=folder is not None
                if folder is None:
                    if require_reuse:
                        raise ValueError('repeat plan missing or stale for '+case_id)
                    print(f'{case_id}: translating...',flush=True)
                    report={}; started=time.perf_counter()
                    args=argparse.Namespace(project_dir=project_root,workbook=workbook,case=case_id,
                        contracts=None,vocabulary=None,output_dir=output,url=url)
                    await run_translation(args,report_sink=report,quiet=True)
                    entry['translation_seconds']=round(time.perf_counter()-started,3)
                    folder=Path(report['output_directory'])
                    entry['translation_folder']=str(folder.resolve())
                    if report['status']!='VALIDATED':
                        entry.update(code='TRANSLATION_REJECTED',reason='TRANSLATION_REJECTED: '+'; '.join(report['errors']),validation_errors=report['errors'])
                        continue
                entry['translation_folder']=str(folder.resolve())
                prepared.append((entry,folder))
                if not faults:
                    await execute(entry,folder,[])
            except Exception as exc:
                entry['reason']=str(exc) if isinstance(exc,ValueError) else type(exc).__name__
            finally:
                entry['duration_seconds']=round(time.perf_counter()-case_start,3)
                if entry['designed_outcome'] is not None:
                    entry['outcome_as_designed']=entry['status']==entry['designed_outcome']
                (output/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2))
        # Preflight targeted faults across all validated plans before any browser launch.
        loaded = [(load_plan(folder)) for _,folder in prepared] if faults else []
        validate_fault_targets(faults,loaded)
        for index,(entry,folder) in enumerate(prepared if faults else []):
            case_id=entry['case_id']
            selected_faults=applicable_faults(faults,loaded[index][0]) if faults else []
            entry['faults_injected']=selected_faults
            await execute(entry,folder,selected_faults)
            entry['duration_seconds']=round(entry['duration_seconds']+entry['execution_seconds'],3)
        statuses=[e['status'] for e in summary['cases']]
        summary['status']='FAILED' if 'FAILED' in statuses else 'BLOCKED' if 'BLOCKED' in statuses else 'PASSED'
    except FaultInputError:
        raise
    except Exception as exc:
        summary['reason']='SUITE_INPUT: '+(str(exc) if isinstance(exc,ValueError) else type(exc).__name__)
    summary['duration_seconds']=round(time.perf_counter()-start,3)
    summary['totals']={s:sum(c['status']==s for c in summary['cases']) for s in ['PASSED','FAILED','BLOCKED']}
    summary['totals']['heals']=sum(c['heals'] for c in summary['cases'])
    for key in ['vision_click_attempts','vision_click_successes']:
        summary['totals'][key]=sum(c.get(key,0) for c in summary['cases'])
    (output/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2))
    build_report(output)
    return summary


def print_summary(summary):
    if summary.get('faults_injected'):
        print('Faults:',summary['faults_injected'])
    print('\nCase ID   Status    As designed  Reason')
    for entry in summary['cases']:
        print(f"{entry['case_id']:<9} {entry['status']:<9} {str(entry['outcome_as_designed']):<12} {entry['reason'] or '-'}")
    print('Totals:',summary['totals'])
    if summary['reason']:
        print(summary['reason'])
    print('Saved:',summary['output_directory'])
