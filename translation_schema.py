"""Typed vocabulary and deterministic validation. No model or browser calls."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)


class AtomicAction(StrictModel):
    action: Literal["navigate", "click", "fill", "select", "press"]
    target: str = Field(min_length=1)
    value: str | None = None

    @model_validator(mode="after")
    def check_arguments(self):
        if not self.target.strip():
            raise ValueError("Action target cannot be blank.")
        if self.action in ("navigate", "fill", "select", "press") and self.value is None:
            raise ValueError(f"{self.action} requires a value.")
        if self.action == "click" and self.value is not None:
            raise ValueError("click does not accept a value.")
        return self


class Assertion(StrictModel):
    kind: Literal["visible", "selected", "input_value", "route_connects", "duration_minutes"]
    target: str = Field(min_length=1)
    value: str | float | int | None = None
    operator: Literal["equals", "less_than"] | None = None

    @model_validator(mode="after")
    def check_arguments(self):
        if not self.target.strip():
            raise ValueError("Assertion target cannot be blank.")
        if self.kind == "duration_minutes":
            if type(self.value) not in (int, float) or self.value <= 0 or self.operator != "less_than":
                raise ValueError("Duration requires a positive numeric minute limit and less_than.")
        elif self.kind == "visible":
            if self.value is not None or self.operator is not None:
                raise ValueError("visible requires null value and operator.")
        elif not isinstance(self.value, str) or not self.value.strip() or self.operator != "equals":
            raise ValueError("Value assertions require text value and equals.")
        return self


class TranslatedStep(StrictModel):
    source_step: int = Field(ge=1)
    source_action: str
    source_expected: str
    actions: list[AtomicAction]
    checks: list[Assertion]


class TranslationPlan(StrictModel):
    case_id: str
    preconditions: str
    steps: list[TranslatedStep]
    cleanup: list[AtomicAction]
    issues: list[str]
    notes: list[str]


def validate_plan(plan: TranslationPlan, case: dict, application_url: str,
                  contract: dict | None = None) -> list[str]:
    """Structural coverage plus optional explicit case acceptance constraints.

    This cannot prove arbitrary natural-language equivalence or locator accuracy.
    """
    errors = []
    if plan.case_id != case["case_id"] or plan.preconditions != case["preconditions"]:
        errors.append("Case ID or preconditions changed.")
    expected_numbers = [item["number"] for item in case["actions"]]
    if [step.source_step for step in plan.steps] != expected_numbers:
        errors.append("Source steps must appear exactly once, in original order.")
    for step in plan.steps:
        index = step.source_step - 1
        if index >= len(case["actions"]):
            continue
        if (step.source_action != case["actions"][index]["text"] or
                step.source_expected != case["expected"][index]["text"]):
            errors.append(f"Step {step.source_step}: original wording changed.")
        if not step.checks:
            errors.append(f"Step {step.source_step}: expected result has no check.")
    actions = [action for step in plan.steps for action in step.actions]
    if not actions or actions[0].action != "navigate" or actions[0].value != application_url:
        errors.append("First action must navigate to the configured application URL.")
    for action in actions + plan.cleanup:
        if action.action == "navigate" and action.value != application_url:
            errors.append("Navigation to an unconfigured URL.")
    if not plan.cleanup:
        errors.append("Post action has no cleanup actions.")
    errors.extend(f"Translator needs clarification: {issue}" for issue in plan.issues)
    if contract:
        # This first OSM contract comes from explicit user-confirmed requirements.
        step = next((s for s in plan.steps if s.source_step == contract["route_step"]), None)
        if step is None:
            errors.append("Missing route-search step.")
        else:
            fills = [a for a in step.actions if a.action == "fill"]
            for city in (contract["origin"], contract["destination"]):
                if sum(a.value == city for a in fills) != 1:
                    errors.append(f"Route step must fill {city} exactly once.")
            for field, city in (("starting-point field", contract["origin"]),
                                ("destination field", contract["destination"])):
                if not any(a.target == field and a.value == city for a in fills):
                    errors.append(f"{field} must receive {city}.")
            if len({a.target.casefold() for a in fills}) != len(fills):
                errors.append("Origin and destination must use distinct fields.")
            submission = [i for i, a in enumerate(step.actions) if a.action in ("click", "press")]
            if len(submission) != 1 or submission[0] <= max(
                    (i for i, a in enumerate(step.actions) if a.action == "fill"), default=-1):
                errors.append("Request directions exactly once, after filling both cities.")
            routes = [c for c in step.checks if c.kind == "route_connects"]
            if not any(all(city in str(c.value) for city in (contract["origin"], contract["destination"])) for c in routes):
                errors.append("Route check must preserve both cities.")
        duration_step = next((s for s in plan.steps if s.source_step == contract["duration_step"]), None)
        duration = [c for c in duration_step.checks if c.kind == "duration_minutes"] if duration_step else []
        if len(duration) != 1 or duration[0].value != contract["limit_minutes"] or duration[0].operator != "less_than":
            errors.append(f"Duration requirement must remain strictly less than {contract['limit_minutes']} minutes.")
        fields_step = next((s for s in plan.steps if s.source_step == contract["fields_step"]), None)
        for target in contract["visible_fields"]:
            if fields_step is None or not any(c.kind == "visible" and c.target == target for c in fields_step.checks):
                errors.append(f"Missing visibility check for {target}.")
        mode_step = next((s for s in plan.steps if s.source_step == contract["mode_step"]), None)
        accepted_modes = {value.casefold() for value in contract["mode_values"]}
        if mode_step is None or not any(c.kind == "selected" and str(c.value).casefold() in accepted_modes
                                        for c in mode_step.checks):
            errors.append("Travel-mode check must assert Car/Driving as the expected value.")
        if mode_step is None or not any(a.action == "select" and str(a.value).casefold() in accepted_modes
                                        for a in mode_step.actions):
            errors.append("Travel-mode action must select Car/Driving.")
        for field in contract["visible_fields"]:
            if not any(a.action == "fill" and a.target == field and a.value == "" for a in plan.cleanup):
                errors.append(f"Cleanup must clear {field}.")
    return errors
