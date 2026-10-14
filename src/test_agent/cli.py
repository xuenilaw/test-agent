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

from test_agent.readers.excel import read_case
from test_agent.schemas.contracts import RouteContract
from test_agent.schemas.plan import TranslationPlan
from test_agent.schemas.vocabulary import TargetVocabulary
from test_agent.translation.validator import validate_plan
from test_agent.translation.translator import translate


def write_json(path: Path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


async def run_translation(args: argparse.Namespace) -> int:
    project_root = args.project_dir.resolve()
    output_root = args.output_dir or project_root / "artifacts"
    run_id = "translation-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    output = output_root.resolve() / run_id / "cases" / args.case
    output.mkdir(parents=True)
    report = {"status": "REJECTED", "browser_executed": False, "contract_applied": False,
              "vocabulary_applied": False,
              "validation_scope": "schema, source coverage, and explicit case constraints; not full semantic equivalence",
              "errors": [], "output_directory": str(output)}
    schema_stage = "Contract schema"
    try:
        case = read_case(args.workbook, args.case)
        contracts_path = args.contracts or args.workbook.parent / "contracts.json"
        # An absent default sidecar means no contract. An explicit path must exist.
        contracts = (json.loads(contracts_path.read_text(encoding="utf-8"))
                     if args.contracts is not None or contracts_path.exists() else {})
        if not isinstance(contracts, dict):
            raise ValueError("Contract file must contain an object keyed by case ID.")
        contract = (RouteContract.model_validate(contracts[args.case]).model_dump()
                    if args.case in contracts else None)
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
            for step in plan.steps:
                print(f"\nSource step {step.source_step}: {step.source_action}")
                for action in step.actions:
                    print(f"  ACTION {action.action}: {action.target} | {action.value!r}")
                for check in step.checks:
                    print(f"  CHECK  {check.kind}: {check.target} | {check.operator} {check.value!r}")
            print("\nCLEANUP", json.dumps([a.model_dump() for a in plan.cleanup]))
    except ValidationError as exc:
        report["errors"] = [f"{schema_stage}: {e['loc']} {e['msg']}" for e in exc.errors(include_input=False)]
    except (ValueError, OSError) as exc:
        report["errors"] = [str(exc)]
    except Exception as exc:
        # Provider responses may contain credentials or request content.
        report["errors"] = [f"Translation failed: {type(exc).__name__}; HTTP {getattr(exc, 'status_code', 'n/a')}"]
    write_json(output / "validation.json", report)
    print("\n" + json.dumps(report, indent=2))
    return 0 if report["status"] == "VALIDATED" else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Natural-language test plans")
    parser.add_argument("--project-dir", type=Path, default=Path.cwd(),
                        help="Directory containing .env, cases/ and artifacts/ (default: current directory)")
    commands = parser.add_subparsers(dest="command", required=True)
    translate_parser = commands.add_parser("translate", help=__doc__)
    translate_parser.add_argument("workbook", type=Path)
    translate_parser.add_argument("--case", default="OSM-001")
    translate_parser.add_argument("--contracts", type=Path, help="Default: contracts.json beside the workbook (optional)")
    translate_parser.add_argument("--vocabulary", type=Path, help="Default: vocabulary.json beside the workbook (optional)")
    translate_parser.add_argument("--output-dir", type=Path, help="Default: <project-dir>/artifacts")
    translate_parser.add_argument("--url", default="https://www.openstreetmap.org/")
    run_parser = commands.add_parser("run", help="Execute a validated translation case folder without AI")
    run_parser.add_argument("folder", type=Path)
    run_parser.add_argument("--locators", type=Path, required=True)
    run_parser.add_argument("--headed", action="store_true")
    run_parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args(argv)
    if args.command == "run":
        from test_agent.runner import run_case
        try:
            result = asyncio.run(run_case(args.folder, args.locators, args.project_dir.resolve(),
                                          headed=args.headed, output_root=args.output_dir))
        except Exception as exc:
            print(f"Input/config error ({type(exc).__name__}): {exc}")
            return 2
        print(result.model_dump_json(indent=2))
        return 0 if result.status == "PASSED" else 1
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", args.case):
        parser.error("Case ID must be a simple identifier, not a filesystem path.")
    return asyncio.run(run_translation(args))
