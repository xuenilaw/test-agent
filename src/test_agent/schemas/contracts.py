"""Validate route-case requirements before asking a model to translate."""

from typing import Annotated, Literal

from pydantic import Field, StringConstraints, TypeAdapter, model_validator

from test_agent.schemas.plan import StrictModel

NonblankText = Annotated[str, StringConstraints(min_length=1, pattern=r"\S")]
Confidence = Annotated[float, Field(gt=0.5, le=1)]


class VisionCheck(StrictModel):
    step: int = Field(ge=1)
    kind: Literal["route_geometry"]
    requirement: NonblankText
    min_confidence: Confidence | dict[NonblankText, Confidence]

    @model_validator(mode='after')
    def thresholds(self):
        if isinstance(self.min_confidence,dict) and not self.min_confidence:
            raise ValueError('Per-provider thresholds cannot be empty')
        return self


def threshold_for(definition, provider):
    """No implicit provider fallback; legacy numeric contracts remain valid."""
    value=definition['min_confidence']
    if isinstance(value,dict):
        if provider not in value:
            raise ValueError(f'Contract has no min_confidence for provider {provider}')
        value=value[provider]
    if type(value) not in (int,float) or not .5 < value <= 1:
        raise ValueError('Contract min_confidence must be >0.5 and <=1')
    return float(value)


class RouteContract(StrictModel):
    type: Literal["route"] = "route"
    designed_outcome: Literal["PASSED", "FAILED"] | None = None
    origin: NonblankText
    destination: NonblankText
    origin_aliases: list[NonblankText] = Field(default_factory=list)
    destination_aliases: list[NonblankText] = Field(default_factory=list)
    route_step: int = Field(ge=1)
    duration_step: int = Field(ge=1)
    limit_minutes: int | float = Field(gt=0)
    fields_step: int = Field(ge=1)
    visible_fields: list[NonblankText] = Field(min_length=1)
    mode_step: int = Field(ge=1)
    mode_values: list[NonblankText] = Field(min_length=1)
    vision_checks: list[VisionCheck] = Field(default_factory=list)

    def validate_case_steps(self, steps: set[int]) -> None:
        declared = [(v.step, v.kind) for v in self.vision_checks]
        if any(step not in steps for step, _ in declared):
            raise ValueError("Vision check step does not exist in the case")
        if len(set(declared)) != len(declared):
            raise ValueError("Duplicate vision check for step/kind")


class LayerContract(StrictModel):
    type: Literal["layer"]
    panel_step: int = Field(ge=1)
    select_step: int = Field(ge=1)
    expected_options: list[NonblankText] = Field(min_length=1)
    selected_layer: NonblankText
    default_layer: NonblankText
    designed_outcome: Literal["PASSED", "FAILED"] | None = None

    def validate_case_steps(self, steps: set[int]) -> None:
        if not {self.panel_step, self.select_step} <= steps:
            raise ValueError("Layer contract step does not exist in the case")
        if not {self.selected_layer, self.default_layer} <= set(self.expected_options):
            raise ValueError("Selected/default layer must be an expected option")


CaseContract = Annotated[RouteContract | LayerContract, Field(discriminator="type")]
CONTRACT_ADAPTER = TypeAdapter(CaseContract)


def parse_contract(data):
    if not isinstance(data, dict):
        raise ValueError("Case contract must be an object")
    return CONTRACT_ADAPTER.validate_python({"type": "route", **data})
