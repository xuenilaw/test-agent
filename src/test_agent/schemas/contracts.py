"""Validate route-case requirements before asking a model to translate."""

from typing import Annotated, Literal

from pydantic import Field, StringConstraints

from test_agent.schemas.plan import StrictModel

NonblankText = Annotated[str, StringConstraints(min_length=1, pattern=r"\S")]


class VisionCheck(StrictModel):
    step: int = Field(ge=1)
    kind: Literal["route_geometry"]
    requirement: NonblankText
    min_confidence: float = Field(gt=0.5, le=1)


class RouteContract(StrictModel):
    origin: NonblankText
    destination: NonblankText
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
