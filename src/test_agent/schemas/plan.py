"""Pure typed plan vocabulary. No case-specific acceptance rules."""

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
    kind: Literal["visible", "selected", "input_value", "route_connects", "duration_minutes", "options_present"]
    target: str = Field(min_length=1)
    value: str | float | int | list[str] | None = None
    operator: Literal["equals", "less_than"] | None = Field(default=None,
        description="Required equals for selected/input_value/route_connects/options_present; less_than for duration_minutes; null only for visible.")

    @model_validator(mode="after")
    def check_arguments(self):
        if not self.target.strip():
            raise ValueError("Assertion target cannot be blank.")
        if self.kind == "duration_minutes":
            if type(self.value) not in (int, float) or self.value <= 0 or self.operator != "less_than":
                raise ValueError("Duration requires a positive numeric minute limit and less_than.")
        elif self.kind == "options_present":
            if (not isinstance(self.value, list) or not self.value or
                    any(not v.strip() for v in self.value) or self.operator != "equals"):
                raise ValueError("options_present requires nonempty text labels and equals")
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
