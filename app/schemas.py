from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, StringConstraints
from typing_extensions import Annotated

Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ExamInput(Input):
    year: int = Field(ge=1900, le=2200)
    exam_part: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=40)]
    title: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]


class DocumentInput(Input):
    filename: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=255)]
    storage_key: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    page_count: int = Field(gt=0)


class AreaInput(Input):
    name: Name
    parent_id: str | None = None


class ThinkerInput(Input):
    canonical_name: Name
    aliases: list[Name] = Field(default_factory=list)
    tradition: Name | None = None
    area_id: str | None = None
    period: Name | None = None


class ConceptInput(Input):
    canonical_name: Name
    aliases: list[Name] = Field(default_factory=list)
    parent_concept_id: str | None = None
    area_id: str | None = None


class TypeInput(Input):
    name: Name


class SourceInput(Input):
    document_id: str
    page_number: int = Field(gt=0)


class QuestionChoice(Input):
    label: Name
    text: str


class QuestionInput(Input):
    exam_id: str
    question_number: int = Field(gt=0)
    question_text: Text
    passage: str | None = None
    choices: list[str | QuestionChoice] = Field(default_factory=list)
    answer_area: str | None = None
    raw_text: Text
    sources: list[SourceInput] = Field(min_length=1)


class EvidenceInput(Input):
    kind: Literal["question", "theory"]
    text: Text
    source_reference: str | None = None


class AnalysisInput(Input):
    area_id: str | None = None
    sub_area_id: str | None = None
    primary_thinkers: list[Name] = Field(default_factory=list)
    related_thinkers: list[Name] = Field(default_factory=list)
    primary_concept: Name | None = None
    sub_concepts: list[Name] = Field(default_factory=list)
    question_types: list[Name] = Field(default_factory=list)
    answer: str | None = None
    explanation: Text
    evidence: list[EvidenceInput] = Field(min_length=1)
    ai_confidence: float | None = Field(default=None, ge=0, le=1)
    model: Name
    analysis_version: Name


class CorrectionInput(AnalysisInput):
    expected_revision: int = Field(gt=0)


class PublishInput(Input):
    expected_publication_id: str | None = None
