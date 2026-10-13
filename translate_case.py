"""Read Excel -> GLM translation -> local validation -> saved plan. No browser."""

import argparse
import asyncio
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
from pydantic import ValidationError

from excel_reader import apply_amendments, read_case
from translation_schema import TranslationPlan, validate_plan
from translator import translate

ROOT = Path(__file__).resolve().parent


def write_json(path: Path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("workbook", type=Path)
    parser.add_argument("--case", default="OSM-001")
    parser.add_argument("--amendments", type=Path, help="Optional explicitly confirmed wording corrections")
    parser.add_argument("--contracts", type=Path, default=ROOT / "translation_contracts.json")
    parser.add_argument("--url", default="https://www.openstreetmap.org/")
    args = parser.parse_args()
    output = ROOT / "artifacts" / ("translation-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ"))
    output.mkdir(parents=True)
    report = {"status": "REJECTED", "browser_executed": False,
              "validation_scope": "schema, source coverage, and explicit case constraints; not full semantic equivalence",
              "errors": [], "output_directory": str(output)}
    try:
        original = read_case(args.workbook, args.case)
        effective, amendments = apply_amendments(original, args.amendments)
        contracts = json.loads(args.contracts.read_text(encoding="utf-8"))
        contract = contracts.get(args.case)
        write_json(output / "source.json", {"original": original, "effective": effective,
                                            "amendments": amendments, "contract": contract,
                                            "application_url": args.url})
        load_dotenv(ROOT / ".env")
        api_key = os.getenv("OPENAI_API_KEY", "").strip()
        model = (os.getenv("OPENAI_MODEL") or os.getenv("OPENAI_DEFAULT_MODEL") or "").strip()
        if not api_key or not model:
            raise ValueError("Set OPENAI_API_KEY and OPENAI_MODEL or OPENAI_DEFAULT_MODEL in .env.")
        raw = await translate(effective, args.url, api_key=api_key, model_name=model,
                              base_url=os.getenv("OPENAI_BASE_URL") or None)
        (output / "model-output.txt").write_text(raw, encoding="utf-8")
        plan = TranslationPlan.model_validate_json(raw)
        report["errors"] = validate_plan(plan, effective, args.url, contract)
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
        report["errors"] = [f"Schema: {e['loc']} {e['msg']}" for e in exc.errors(include_input=False)]
    except (ValueError, OSError) as exc:
        report["errors"] = [str(exc)]
    except Exception as exc:
        # Provider responses may contain credentials or request content.
        report["errors"] = [f"Translation failed: {type(exc).__name__}; HTTP {getattr(exc, 'status_code', 'n/a')}"]
    write_json(output / "validation.json", report)
    print("\n" + json.dumps(report, indent=2))
    return 0 if report["status"] == "VALIDATED" else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
