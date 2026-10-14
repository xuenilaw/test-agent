"""Suite target names are declared independently of DOM locator mappings."""

from pydantic import Field
from test_agent.schemas.contracts import NonblankText
from test_agent.schemas.plan import StrictModel


class TargetVocabulary(StrictModel):
    targets: dict[NonblankText, NonblankText] = Field(min_length=1)
    hints: list[NonblankText] = Field(default_factory=list)
