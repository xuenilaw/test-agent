"""Typed execution evidence, separate from translation validation."""

from typing import Literal
from pydantic import Field
from test_agent.schemas.plan import StrictModel

Status = Literal["PASSED", "FAILED", "BLOCKED", "NOT_RUN"]


class CheckResult(StrictModel):
    kind: str
    target: str
    expected: dict
    actual: dict = Field(default_factory=dict)
    status: Status = "NOT_RUN"
    reason: str | None = None


class StepResult(StrictModel):
    source_step: int
    status: Status = "NOT_RUN"
    reason: str | None = None
    details: dict = Field(default_factory=dict)
    actions: list[dict] = Field(default_factory=list)
    checks: list[CheckResult] = Field(default_factory=list)
    screenshot: str | None = None


class CaseResult(StrictModel):
    case_id: str
    status: Status = "BLOCKED"
    translation_folder: str
    output_directory: str
    steps: list[StepResult]
    cleanup: list[dict] = Field(default_factory=list)
    evidence_errors: list[str] = Field(default_factory=list)
    reason: str | None = None
    route_geometry_verified: bool = False
