"""Validate route-case requirements before asking a model to translate."""

from typing import Annotated, Literal

from pydantic import Field, StringConstraints, TypeAdapter

from test_agent.schemas.plan import StrictModel

NonblankText = Annotated[str, StringConstraints(min_length=1, pattern=r"\S")]


class VisionCheck(StrictModel):
    step: int = Field(ge=1)
    kind: Literal["route_geometry"]
    requirement: NonblankText
    min_confidence: float = Field(gt=0.5, le=1)


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
