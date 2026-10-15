"""Revalidate disk plans and current requirements before any browser launch."""

import json
import re
from pathlib import Path
from test_agent.readers.excel import read_case
from test_agent.schemas.contracts import RouteContract
from test_agent.schemas.plan import TranslationPlan
from test_agent.schemas.vocabulary import TargetVocabulary
from test_agent.translation.validator import validate_plan


def load_plan(folder: Path, *, revalidate=False) -> tuple[TranslationPlan, dict]:
    report = json.loads((folder / "validation.json").read_text(encoding="utf-8"))
    if report.get("status") != "VALIDATED" or report.get("errors"):
        raise ValueError("Translation is not VALIDATED; regenerate the plan.")
    plan = TranslationPlan.model_validate_json((folder / "plan.json").read_text(encoding="utf-8"))
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", plan.case_id):
        raise ValueError("Invalid case ID.")
    source = json.loads((folder / "source.json").read_text(encoding="utf-8"))
    if "case" not in source:
        raise ValueError("Old translation source format; translate again without amendments.")
    case = source["case"]
    workbook = Path(case["source"]["file"])
    current = read_case(workbook, plan.case_id)
    if {k: v for k, v in current.items() if k != "source"} != {k: v for k, v in case.items() if k != "source"}:
        raise ValueError("Workbook requirements changed; translate again.")
    path = Path(source.get("contract_file", workbook.parent / "contracts.json"))
    contracts = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    if not isinstance(contracts, dict):
        raise ValueError("Contract file must be an object.")
    typed_contract = RouteContract.model_validate(contracts[plan.case_id]) if plan.case_id in contracts else None
    if typed_contract:
        typed_contract.validate_case_steps({s["number"] for s in current["actions"]})
    contract = typed_contract.model_dump() if typed_contract else None
    saved = source.get("contract")
    saved = RouteContract.model_validate(saved).model_dump() if saved is not None else None
    if contract != saved and not revalidate:
        raise ValueError("Contract requirements changed; translate again.")
    vocabulary = None
    if "vocabulary_file" in source:
        path = Path(source["vocabulary_file"])
        vocabulary = (TargetVocabulary.model_validate_json(path.read_text(encoding="utf-8")).model_dump()
                      if path.exists() else None)
        if vocabulary != source.get("vocabulary") and not revalidate:
            raise ValueError("Target vocabulary changed; translate again.")
    errors = validate_plan(plan, current, source["application_url"], contract,
                           set(vocabulary["targets"]) if vocabulary is not None else None)
    if errors:
        raise ValueError("Loaded plan rejected: " + "; ".join(errors))
    source["contract"] = contract
    source["case"] = current
    if "vocabulary_file" in source:
        source["vocabulary"] = vocabulary
    return plan, source
