"""Validate route-case requirements before asking a model to translate."""

from typing import Annotated

from pydantic import Field, StringConstraints

from test_agent.schemas.plan import StrictModel

NonblankText = Annotated[str, StringConstraints(min_length=1, pattern=r"\S")]


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
