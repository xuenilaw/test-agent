"""Read Excel -> GLM translation -> local validation -> saved plan. No browser."""

import argparse
import asyncio
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
from pydantic import ValidationError

from test_agent.guardrail import check_workbook, save_check, print_check
from test_agent.readers.excel import read_case
from test_agent.schemas.contracts import parse_contract
from test_agent.schemas.plan import TranslationPlan
from test_agent.schemas.vocabulary import TargetVocabulary
from test_agent.translation.validator import validate_plan
from test_agent.translation.translator import translate


def write_json(path: Path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def run_revalidation(args) -> int:
    from test_agent.plan_loader import load_plan
    from test_agent.reporting import read_json
    case_id = read_json(args.folder / 'plan.json').get('case_id', args.folder.name)
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", case_id):
        case_id = "invalid-case"
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    output = (args.output_dir or args.project_dir / "artifacts").resolve() / ("translation-" + stamp) / "cases" / case_id
    output.mkdir(parents=True)
    report = {"status": "REJECTED", "browser_executed": False, "model_called": False,
              "errors": [], "output_directory": str(output),
              "validation_scope": "schema, unchanged source coverage, current contract and vocabulary; not full semantic equivalence"}
    try:
        plan, source = load_plan(args.folder, revalidate=True)
        if plan.case_id != case_id:
            raise ValueError("Folder name must match case ID")
        source["revalidated_from"] = str(args.folder.resolve())
        write_json(output / "source.json", source)
        write_json(output / "plan.json", plan.model_dump())
        report.update(status="VALIDATED", contract_applied=source.get("contract") is not None,
                      vocabulary_applied=source.get("vocabulary") is not None)
    except ValidationError as exc:
        report["errors"] = [f"Schema: {e['loc']} {e['msg']}" for e in exc.errors(include_input=False)]
    except (ValueError, OSError, KeyError) as exc:
        report["errors"] = [str(exc)]
    write_json(output / "validation.json", report)
    print(json.dumps(report, indent=2))
    return 0 if report["status"] == "VALIDATED" else 1


async def run_translation(args: argparse.Namespace, *, report_sink=None, quiet=False) -> int:
    project_root = args.project_dir.resolve()
    output_root = args.output_dir or project_root / "artifacts"
    run_id = "translation-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    guard = check_workbook(args.workbook,url=args.url,case_id=args.case)
    # A blocked case ID may itself be a secret. Keep blocked artifacts at the run root.
    output = (output_root.resolve()/run_id if guard['status']=='BLOCKED' else
              getattr(args, 'output_folder', None) or output_root.resolve()/run_id/'cases'/args.case)
    output.mkdir(parents=True)
    report = {"status": "REJECTED", "browser_executed": False, "contract_applied": False,
              "vocabulary_applied": False,
              "validation_scope": "schema, source coverage, and explicit case constraints; not full semantic equivalence",
              "errors": [], "output_directory": str(output)}
    save_check(guard,output)
    if guard['status']=='BLOCKED':
        print_check(guard)
        if report_sink is not None:
            report_sink.update(status='BLOCKED_BY_GUARDRAIL',errors=['Guardrail blocked'],output_directory=str(output))
        return 3
    schema_stage = "Contract schema"
    try:
        case = read_case(args.workbook, args.case)
        args.url = guard["application_urls"][args.case]
        contracts_path = args.contracts or args.workbook.parent / "contracts.json"
        # An absent default sidecar means no contract. An explicit path must exist.
        contracts = (json.loads(contracts_path.read_text(encoding="utf-8"))
                     if args.contracts is not None or contracts_path.exists() else {})
        if not isinstance(contracts, dict):
            raise ValueError("Contract file must contain an object keyed by case ID.")
        typed_contract = parse_contract(contracts[args.case]) if args.case in contracts else None
        if typed_contract:
            typed_contract.validate_case_steps({s["number"] for s in case["actions"]})
        contract = typed_contract.model_dump() if typed_contract else None
        vocabulary_path = args.vocabulary or args.workbook.parent / "vocabulary.json"
        schema_stage = "Vocabulary schema"
        vocabulary = (TargetVocabulary.model_validate_json(vocabulary_path.read_text(encoding="utf-8")).model_dump()
                      if args.vocabulary is not None or vocabulary_path.exists() else None)
        write_json(output / "source.json", {"case": case, "contract": contract,
                                            "contract_file": str(contracts_path.resolve()),
                                            "vocabulary": vocabulary, "vocabulary_file": str(vocabulary_path.resolve()),
                                            "application_url": args.url})
        load_dotenv(project_root / ".env")
        api_key = os.getenv("OPENAI_API_KEY", "").strip()
        model = (os.getenv("OPENAI_MODEL") or os.getenv("OPENAI_DEFAULT_MODEL") or "").strip()
        if not api_key or not model:
            raise ValueError("Set OPENAI_API_KEY and OPENAI_MODEL or OPENAI_DEFAULT_MODEL in .env.")
        raw = await translate(case, args.url, api_key=api_key, model_name=model,
                              base_url=os.getenv("OPENAI_BASE_URL") or None, vocabulary=vocabulary)
        (output / "model-output.txt").write_text(raw, encoding="utf-8")
        schema_stage = "Plan schema"
        plan = TranslationPlan.model_validate_json(raw)
        report["errors"] = validate_plan(plan, case, args.url, contract,
                                         set(vocabulary["targets"]) if vocabulary is not None else None)
        report["contract_applied"] = contract is not None
        report["vocabulary_applied"] = vocabulary is not None
        report["notes"] = plan.notes
        write_json(output / "candidate-plan.json", plan.model_dump())
        if not report["errors"]:
            report["status"] = "VALIDATED"
            write_json(output / "plan.json", plan.model_dump())
            for step in ([] if quiet else plan.steps):
                print(f"\nSource step {step.source_step}: {step.source_action}")
                for action in step.actions:
                    print(f"  ACTION {action.action}: {action.target} | {action.value!r}")
                for check in step.checks:
                    print(f"  CHECK  {check.kind}: {check.target} | {check.operator} {check.value!r}")
            if not quiet:
                print("\nCLEANUP", json.dumps([a.model_dump() for a in plan.cleanup]))
    except ValidationError as exc:
        report["errors"] = [f"{schema_stage}: {e['loc']} {e['msg']}" for e in exc.errors(include_input=False)]
    except (ValueError, OSError) as exc:
        report["errors"] = [str(exc)]
    except Exception as exc:
        # Provider responses may contain credentials or request content.
        report["errors"] = [f"Translation failed: {type(exc).__name__}; HTTP {getattr(exc, 'status_code', 'n/a')}"]
    write_json(output / "validation.json", report)
    if report_sink is not None:
        report_sink.update(report)
    if not quiet:
        print("\n" + json.dumps(report, indent=2))
    return 0 if report["status"] == "VALIDATED" else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Natural-language test plans")
    parser.add_argument("--project-dir", type=Path, default=Path.cwd(),
                        help="Directory containing .env, cases/ and artifacts/ (default: current directory)")
    commands = parser.add_subparsers(dest="command", required=True)
    guard_parser = commands.add_parser('guardrail',help='Offline whole-workbook input guardrail; blocked exits 3')
    guard_parser.add_argument('workbook',type=Path)
    guard_parser.add_argument('--output-dir',type=Path)
    guard_parser.add_argument('--url')
    commands.add_parser('clef-smoke',help='One text-only OpenRouter Decisions request (no images)')
    analyst_parser = commands.add_parser('audit-agent',help='Read-only Claude Haiku audit with guarded screenshot questions')
    analyst_parser.add_argument('folder',type=Path)
    analyst_parser.add_argument('--unavailable',action='store_true',help='Record unanalysed cases without model requests (CI configuration failure)')
    jira_parser = commands.add_parser('jira',help='Approval-gated Jira export (offline dry-run by default)')
    jira_commands = jira_parser.add_subparsers(dest='jira_command',required=True)
    jira_commands.add_parser('check',help='Read-only Jira authentication, project and issue-type check')
    jira_create = jira_commands.add_parser('create')
    jira_create.add_argument('folder',type=Path)
    jira_create.add_argument('--approved',required=True,help='Comma-separated finding IDs explicitly approved by the human')
    jira_mode = jira_create.add_mutually_exclusive_group()
    jira_mode.add_argument('--dry-run',action='store_true')
    jira_mode.add_argument('--send',action='store_true',help='Send only explicitly approved, validated findings to Jira')
    report_parser=commands.add_parser('report',help='Build offline HTML from a saved suite or repeat folder')
    report_parser.add_argument('folder',type=Path)
    audit_parser=commands.add_parser('audit',help='Build spreadsheet-safe audit.csv from saved suite or repeat evidence')
    audit_parser.add_argument('folder',type=Path)
    for command, help_text in [('junit','Build step-level JUnit XML from saved results'),
                               ('package','Prepare five named Jenkins report downloads')]:
        sub = commands.add_parser(command, help=help_text)
        sub.add_argument('folder', type=Path)
        if command == 'package':
            sub.add_argument('--output-dir', type=Path, default=Path('reports'))
    prune_parser = commands.add_parser('prune', help='Preview old artifact deletion; --yes deletes')
    prune_parser.add_argument('--keep', type=int, default=10)
    prune_parser.add_argument('--yes', action='store_true')
    repeat_parser=commands.add_parser('repeat',help='Repeat execution with current validated plans, without translation')
    repeat_parser.add_argument('workbook',type=Path)
    repeat_parser.add_argument('--locators',type=Path,required=True)
    repeat_parser.add_argument('--times',type=int,default=3)
    repeat_parser.add_argument('--reuse',action='store_true',help='Always enforced for repeat; missing/stale plans are rejected')
    repeat_parser.add_argument('--headed',action='store_true')
    repeat_parser.add_argument('--output-dir',type=Path)
    translate_parser = commands.add_parser("translate", help=__doc__)
    translate_parser.add_argument("workbook", type=Path)
    translate_parser.add_argument("--case", default="OSM-001")
    translate_parser.add_argument("--contracts", type=Path, help="Default: contracts.json beside the workbook (optional)")
    translate_parser.add_argument("--vocabulary", type=Path, help="Default: vocabulary.json beside the workbook (optional)")
    translate_parser.add_argument("--output-dir", type=Path, help="Default: <project-dir>/artifacts")
    translate_parser.add_argument("--url", help="Must equal the case app URL in guardrail.json")
    revalidate_parser = commands.add_parser("revalidate", help="Revalidate an unchanged translated case against current requirements, without LLM")
    revalidate_parser.add_argument("folder", type=Path)
    revalidate_parser.add_argument("--output-dir", type=Path)
    suite_parser = commands.add_parser("suite", help="Translate and execute all workbook cases in order")
    suite_parser.add_argument("workbook", type=Path)
    suite_parser.add_argument("--locators", type=Path, required=True)
    suite_parser.add_argument("--url", help="Must equal each case app URL in guardrail.json")
    suite_parser.add_argument("--reuse", action="store_true")
    suite_parser.add_argument("--fault", action="append", default=[])
    suite_parser.add_argument("--skip-vision", action="store_true")
    suite_parser.add_argument("--headed", action="store_true")
    suite_parser.add_argument("--output-dir", type=Path)
    calibration_parser = commands.add_parser("calibrate", help="Capture once or measure a frozen labelled vision set")
    calibration_commands = calibration_parser.add_subparsers(dest="calibration_command", required=True)
    capture_parser = calibration_commands.add_parser("capture")
    capture_parser.add_argument("folder", type=Path, nargs="?", default=Path("cases/osm/vision_calibration"))
    capture_parser.add_argument("--locators", type=Path, default=Path("cases/osm/locators.json"))
    capture_parser.add_argument("--headed", action="store_true")
    capture_parser.add_argument("--only", help="Capture one named preset into a missing file; never overwrite")
    capture_parser.add_argument("--profile", choices=["original", "holdout"], default="original")
    calibrate_run_parser = calibration_commands.add_parser("run")
    calibrate_run_parser.add_argument("folder", type=Path)
    calibrate_run_parser.add_argument("--runs", type=int, default=5)
    calibrate_run_parser.add_argument("--contracts", type=Path, default=Path("cases/osm/contracts.json"))
    calibrate_run_parser.add_argument("--case", default="OSM-001")
    calibrate_run_parser.add_argument("--output-dir", type=Path)
    calibrate_run_parser.add_argument('--image-variant',choices=['png','jpeg'],default='png')
    compress_parser=calibration_commands.add_parser('compress',help='Freeze deterministic JPEG copies of labelled PNGs')
    compress_parser.add_argument('folder',type=Path)
    run_parser = commands.add_parser("run", help="Execute a validated plan including contract-declared vision checks")
    run_parser.add_argument("folder", type=Path)
    run_parser.add_argument("--locators", type=Path, required=True)
    run_parser.add_argument("--headed", action="store_true")
    run_parser.add_argument("--fault", action="append", default=[])
    run_parser.add_argument("--output-dir", type=Path)
    run_parser.add_argument("--skip-vision", action="store_true", help="Skip declared vision checks as BLOCKED for offline/dev runs")
    args = parser.parse_args(argv)
    if args.command=='guardrail':
        result = check_workbook(args.workbook,url=args.url)
        output = args.output_dir or args.project_dir/'artifacts'/('guardrail-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'))
        save_check(result,output)
        print_check(result)
        print('Saved:',output.resolve())
        return 3 if result['status']=='BLOCKED' else 0
    if args.command == 'audit-agent':
        from test_agent.audit_agent import run_audit_agent, approval_preview
        from test_agent.reporting import build_report
        load_dotenv(args.project_dir.resolve()/'.env')
        try:
            async def unavailable(*unused):
                raise ValueError('AUDIT_CONFIG')
            analysis = asyncio.run(run_audit_agent(args.folder,analyst=unavailable if args.unavailable else None))
            preview = approval_preview(args.folder)
            if preview['credential_warning']:
                print(preview['credential_warning'])
            build_report(args.folder)
            print('Saved audit_analysis.json and audit_analysis.md')
            print(f"Audit model: {analysis['text_model']} (Anthropic); findings: {len(analysis['findings'])}; dropped: {len(analysis['dropped_findings'])}")
            print(preview['summary'])
            if preview['banner']:
                print(preview['banner'])
        except Exception:
            print('AUDIT_UNAVAILABLE: inspect saved suite evidence; no tickets recommended')
        return 0
    if args.command == 'jira':
        from test_agent.jira import create_tickets, check_connection, error_line
        load_dotenv(args.project_dir.resolve()/'.env')
        if args.jira_command=='check':
            result = check_connection()
            for check in result['checks']:
                detail = check.get('display_name') or ', '.join(check.get('issue_types',[]))
                print(f"Jira {check['phase']}: {check['status']}"+(' — '+detail if detail else ''))
            for error in result['errors']:
                print(error_line(error,os.getenv('JIRA_PROJECT','WBSFP')))
            return 1 if result['errors'] else 0
        result = create_tickets(args.folder,list(dict.fromkeys(i.strip() for i in args.approved.split(',') if i.strip())),send=args.send)
        for error in result['errors']:
            print(error_line(error,os.getenv('JIRA_PROJECT','WBSFP')))
        print(json.dumps(result,indent=2))
        return 1 if result['errors'] else 0
    if args.command in {'report','repeat','audit','junit','package','prune'}:
        try:
            if args.command == 'prune':
                from test_agent.artifacts import prune
                for path in prune(args.project_dir / 'artifacts', keep=args.keep, yes=args.yes):
                    print(('Deleted: ' if args.yes else 'Would delete: ') + str(path))
                return 0
            if args.command == 'package':
                from test_agent.artifacts import package_reports
                print(package_reports(args.folder, args.output_dir)); return 0
            if args.command == 'junit':
                from test_agent.junit import build_junit
                print(build_junit(args.folder)); return 0
            if args.command=='audit':
                from test_agent.audit import build_audit
                print(build_audit(args.folder));return 0
            if args.command=='report':
                from test_agent.reporting import build_report
                print(build_report(args.folder));return 0
            from test_agent.repeatability import run_repeat
            result=asyncio.run(run_repeat(args.workbook,args.locators,args.project_dir.resolve(),times=args.times,
                                          headed=args.headed,output_root=args.output_dir))
            print(json.dumps(dict(cases=result['cases'],output_directory=result['output_directory']),ensure_ascii=False,indent=2))
            return 0 if result['summary']['status']=='PASSED' else 1
        except (ValueError,OSError) as exc:
            print(str(exc));return 2
    if args.command == 'clef-smoke':
        from test_agent.verification.clef import smoke
        return asyncio.run(smoke(args.project_dir.resolve()))
    if args.command == 'run':
        from test_agent.faults import validate_fault_names
        try:
            validate_fault_names(args.fault)
        except ValueError as exc:
            print(str(exc))
            return 2
    if args.command == "suite":
        from test_agent.suite import run_suite, print_summary
        try:
            summary = asyncio.run(run_suite(args.workbook, args.locators, args.project_dir.resolve(), reuse=args.reuse,
                skip_vision=args.skip_vision, headed=args.headed, output_root=args.output_dir, faults=args.fault,url=args.url))
        except ValueError as exc:
            print(str(exc))
            return 2
        if summary['status']=='BLOCKED_BY_GUARDRAIL':
            return 3
        print_summary(summary)
        return 0 if summary["status"] == "PASSED" else 1
    if args.command == "revalidate":
        return run_revalidation(args)
    if args.command == "calibrate":
        try:
            if args.calibration_command == 'compress':
                from test_agent.verification.compression import freeze_compressed
                print(json.dumps(freeze_compressed(args.folder),ensure_ascii=False,indent=2))
            elif args.calibration_command == "capture":
                from test_agent.verification.calibration_capture import capture_set
                labels = asyncio.run(capture_set(args.folder, args.locators, args.project_dir.resolve(), headed=args.headed, only=args.only, profile=args.profile))
                print(f"Captured {len(labels)} images in {args.folder}")
            else:
                from test_agent.verification.calibration import run_calibration, load_labels
                from test_agent.verification.vision_providers import provider_from_env
                load_labels(args.folder)  # Reject bad labels before any API call.
                load_dotenv(args.project_dir.resolve() / ".env")
                contract = json.loads(args.contracts.read_text(encoding="utf-8"))[args.case]
                output, report = asyncio.run(run_calibration(args.folder, provider=provider_from_env(),
                    contract=contract, project_root=args.project_dir.resolve(), runs=args.runs, output_root=args.output_dir,image_variant=args.image_variant))
                print(report)
                print(f"Saved: {output.resolve()}")
            return 0
        except Exception as exc:
            print(f"Calibration failed: {type(exc).__name__}")
            return 1
    if args.command == "run":
        from test_agent.runner import run_case
        try:
            result = asyncio.run(run_case(args.folder, args.locators, args.project_dir.resolve(),
                                          headed=args.headed, output_root=args.output_dir,
                                          skip_vision=args.skip_vision, faults=args.fault))
        except Exception as exc:
            print(f"Input/config error ({type(exc).__name__}): {exc}")
            return 2
        print(result.model_dump_json(indent=2))
        return 0 if result.status == "PASSED" else 1
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", args.case):
        parser.error("Case ID must be a simple identifier, not a filesystem path.")
    return asyncio.run(run_translation(args))
