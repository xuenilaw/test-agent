"""Untrusted analyst output: syntax is checked here, evidence is checked separately."""
from typing import Literal
from pydantic import Field, field_validator
from test_agent.schemas.plan import StrictModel

Cause = Literal['software_bug', 'test_case_problem', 'test_tool_problem', 'environment_problem',
                'possible_false_pass', 'needs_human_review', 'confirmed_pass']


class TextModel(StrictModel):
    @field_validator("*", mode="before")
    @classmethod
    def truncate_text(cls, value, info):
        limits = {"summary":800, "title":120, "explanation":800,
                  "short_reason":160, "screenshot_observations":400, "suggested_next_step":300, "why":400, "observation":300}
        if info.field_name=='short_reason' and isinstance(value,str):
            value = ' '.join(value.split())
        return value[:limits[info.field_name]] if isinstance(value,str) and info.field_name in limits else value


class Alternative(TextModel):
    cause: Cause
    why: str = Field(min_length=1, max_length=400)


class Finding(TextModel):
    finding_id: str = Field(pattern=r'^F[A-Za-z0-9_-]{1,60}$')
    case_id: str = Field(pattern=r'^[A-Za-z0-9][A-Za-z0-9_.-]*$')
    step: int | None = Field(default=None, ge=1)
    title: str = Field(min_length=1, max_length=120)
    likely_cause: Cause
    confidence: Literal['low', 'medium', 'high']
    short_reason: str = Field(min_length=1, max_length=160, description='One sentence explaining why this finding matters.')
    explanation: str = Field(min_length=1, max_length=800)
    alternative_causes: list[Alternative] = Field(max_length=3)
    screenshot_observations: str = Field(max_length=400)
    suggested_next_step: str = Field(min_length=1, max_length=300)
    evidence_rows: list[str] = Field(max_length=50)
    evidence_screenshots: list[str] = Field(max_length=20)
    evidence_questions: list[str] = Field(max_length=25)
    recommend_ticket: bool
    ticket_type: Literal['bug', 'test_case_fix'] | None
    severity: Literal['low', 'medium', 'high']


class CaseAnalysis(TextModel):
    summary: str = Field(min_length=1, max_length=800)
    findings: list[Finding] = Field(min_length=1, max_length=12)


class ScreenshotAnswer(TextModel):
    choice: str = Field(min_length=1, max_length=100)
    confidence: float = Field(ge=0, le=1)
    observation: str = Field(max_length=300)


class AnalysisEnvelope(TextModel):
    summary: str = Field(min_length=1, max_length=800)
    findings: list[object] = Field(min_length=1, max_length=12)


def submission_schema():
    """Exact structural schema; unsupported strict-tool limits remain Python checks.

    https://platform.claude.com/docs/en/build-with-claude/structured-outputs
    """
    def supported(node):
        if isinstance(node,list):
            return [supported(item) for item in node]
        if not isinstance(node,dict):
            return node
        limits = {k:v for k,v in node.items() if k in
                  {'minimum','maximum','minLength','maxLength','maxItems','minItems'}}
        result = {k:supported(v) for k,v in node.items() if k not in limits}
        if limits:
            result['description'] = (result.get('description','')+' Python validates: '+str(limits)).strip()
        return result
    return supported(CaseAnalysis.model_json_schema())
