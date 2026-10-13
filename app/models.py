from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import JSON, CheckConstraint, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base


def new_id():
    return str(uuid4())


def now():
    return datetime.now(timezone.utc)


class Identity:
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)


class Exam(Identity, Base):
    __tablename__ = "exams"
    __table_args__ = (UniqueConstraint("year", "exam_part"), CheckConstraint("year >= 1900 AND year <= 2200"))
    exam_id: Mapped[str] = mapped_column(String(80), unique=True)
    year: Mapped[int] = mapped_column(Integer)
    exam_part: Mapped[str] = mapped_column(String(40))
    title: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Document(Identity, Base):
    __tablename__ = "documents"
    __table_args__ = (CheckConstraint("page_count > 0"),)
    filename: Mapped[str] = mapped_column(String(255))
    storage_key: Mapped[str] = mapped_column(String(500), unique=True)
    sha256: Mapped[str] = mapped_column(String(64))
    page_count: Mapped[int] = mapped_column(Integer)
    uploaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class ExamDocument(Base):
    __tablename__ = "exam_documents"
    exam_id: Mapped[str] = mapped_column(ForeignKey("exams.id", ondelete="RESTRICT"), primary_key=True)
    document_id: Mapped[str] = mapped_column(ForeignKey("documents.id", ondelete="RESTRICT"), primary_key=True)


class Area(Identity, Base):
    __tablename__ = "areas"
    name: Mapped[str] = mapped_column(String(100), unique=True)
    parent_id: Mapped[str | None] = mapped_column(ForeignKey("areas.id", ondelete="RESTRICT"))


class Thinker(Identity, Base):
    __tablename__ = "thinkers"
    canonical_name: Mapped[str] = mapped_column(String(100), unique=True)
    aliases: Mapped[list] = mapped_column(JSON, default=list)
    tradition: Mapped[str | None] = mapped_column(String(100))
    area_id: Mapped[str | None] = mapped_column(ForeignKey("areas.id", ondelete="RESTRICT"))
    period: Mapped[str | None] = mapped_column(String(100))


class ThinkerAlias(Base):
    __tablename__ = "thinker_aliases"
    normalized_alias: Mapped[str] = mapped_column(String(200), primary_key=True)
    thinker_id: Mapped[str] = mapped_column(ForeignKey("thinkers.id", ondelete="CASCADE"))


class Concept(Identity, Base):
    __tablename__ = "concepts"
    canonical_name: Mapped[str] = mapped_column(String(100), unique=True)
    aliases: Mapped[list] = mapped_column(JSON, default=list)
    parent_concept_id: Mapped[str | None] = mapped_column(ForeignKey("concepts.id", ondelete="RESTRICT"))
    area_id: Mapped[str | None] = mapped_column(ForeignKey("areas.id", ondelete="RESTRICT"))


class ConceptAlias(Base):
    __tablename__ = "concept_aliases"
    normalized_alias: Mapped[str] = mapped_column(String(200), primary_key=True)
    concept_id: Mapped[str] = mapped_column(ForeignKey("concepts.id", ondelete="CASCADE"))


class ConceptThinker(Base):
    __tablename__ = "concept_thinkers"
    concept_id: Mapped[str] = mapped_column(ForeignKey("concepts.id", ondelete="CASCADE"), primary_key=True)
    thinker_id: Mapped[str] = mapped_column(ForeignKey("thinkers.id", ondelete="RESTRICT"), primary_key=True)


class QuestionType(Identity, Base):
    __tablename__ = "question_types"
    name: Mapped[str] = mapped_column(String(100), unique=True)


class Question(Identity, Base):
    __tablename__ = "questions"
    __table_args__ = (UniqueConstraint("exam_id", "question_number"), CheckConstraint("question_number > 0"))
    exam_id: Mapped[str] = mapped_column(ForeignKey("exams.id", ondelete="RESTRICT"))
    question_number: Mapped[int] = mapped_column(Integer)
    question_text: Mapped[str] = mapped_column(Text)
    passage: Mapped[str | None] = mapped_column(Text)
    choices: Mapped[list] = mapped_column(JSON, default=list)
    answer_area: Mapped[str | None] = mapped_column(Text)
    raw_text: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class QuestionSource(Base):
    __tablename__ = "question_sources"
    __table_args__ = (CheckConstraint("page_number > 0"),)
    question_id: Mapped[str] = mapped_column(ForeignKey("questions.id", ondelete="CASCADE"), primary_key=True)
    document_id: Mapped[str] = mapped_column(ForeignKey("documents.id", ondelete="RESTRICT"), primary_key=True)
    page_number: Mapped[int] = mapped_column(Integer, primary_key=True)


class Analysis(Identity, Base):
    __tablename__ = "question_analyses"
    __table_args__ = (
        UniqueConstraint("question_id", "revision_number"),
        CheckConstraint("review_status IN ('unreviewed', 'confirmed', 'corrected')"),
        CheckConstraint("origin IN ('ai', 'human')"),
        CheckConstraint("ai_confidence IS NULL OR (ai_confidence >= 0 AND ai_confidence <= 1)"),
    )
    question_id: Mapped[str] = mapped_column(ForeignKey("questions.id", ondelete="CASCADE"))
    revision_number: Mapped[int] = mapped_column(Integer)
    parent_analysis_id: Mapped[str | None] = mapped_column(ForeignKey("question_analyses.id", ondelete="RESTRICT"))
    origin: Mapped[str] = mapped_column(String(10), default="ai")
    area_id: Mapped[str | None] = mapped_column(ForeignKey("areas.id", ondelete="RESTRICT"))
    sub_area_id: Mapped[str | None] = mapped_column(ForeignKey("areas.id", ondelete="RESTRICT"))
    answer: Mapped[str | None] = mapped_column(Text)
    explanation: Mapped[str] = mapped_column(Text)
    ai_confidence: Mapped[float | None]
    review_status: Mapped[str] = mapped_column(String(20), default="unreviewed")
    model: Mapped[str] = mapped_column(String(100))
    analysis_version: Mapped[str] = mapped_column(String(100))
    analysis_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class AnalysisThinker(Base):
    __tablename__ = "analysis_thinkers"
    __table_args__ = (CheckConstraint("role IN ('primary', 'related')"),)
    analysis_id: Mapped[str] = mapped_column(ForeignKey("question_analyses.id", ondelete="CASCADE"), primary_key=True)
    thinker_id: Mapped[str] = mapped_column(ForeignKey("thinkers.id", ondelete="RESTRICT"), primary_key=True)
    role: Mapped[str] = mapped_column(String(10))


class AnalysisConcept(Base):
    __tablename__ = "analysis_concepts"
    __table_args__ = (CheckConstraint("role IN ('primary', 'sub')"),)
    analysis_id: Mapped[str] = mapped_column(ForeignKey("question_analyses.id", ondelete="CASCADE"), primary_key=True)
    concept_id: Mapped[str] = mapped_column(ForeignKey("concepts.id", ondelete="RESTRICT"), primary_key=True)
    role: Mapped[str] = mapped_column(String(10))


class AnalysisType(Base):
    __tablename__ = "analysis_types"
    analysis_id: Mapped[str] = mapped_column(ForeignKey("question_analyses.id", ondelete="CASCADE"), primary_key=True)
    question_type_id: Mapped[str] = mapped_column(ForeignKey("question_types.id", ondelete="RESTRICT"), primary_key=True)


class Evidence(Identity, Base):
    __tablename__ = "analysis_evidence"
    __table_args__ = (CheckConstraint("kind IN ('question', 'theory')"),)
    analysis_id: Mapped[str] = mapped_column(ForeignKey("question_analyses.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(String(10))
    text: Mapped[str] = mapped_column(Text)
    source_reference: Mapped[str | None] = mapped_column(Text)


class Publication(Base):
    __tablename__ = "question_publications"
    question_id: Mapped[str] = mapped_column(ForeignKey("questions.id", ondelete="RESTRICT"), primary_key=True)
    analysis_id: Mapped[str] = mapped_column(ForeignKey("question_analyses.id", ondelete="RESTRICT"), unique=True)
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class ReviewEvent(Identity, Base):
    __tablename__ = "review_events"
    analysis_id: Mapped[str] = mapped_column(ForeignKey("question_analyses.id", ondelete="RESTRICT"))
    action: Mapped[str] = mapped_column(String(30))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class ExtractionRun(Identity, Base):
    __tablename__ = "extraction_runs"
    document_id: Mapped[str] = mapped_column(ForeignKey("documents.id", ondelete="RESTRICT"))
    exam_id: Mapped[str] = mapped_column(ForeignKey("exams.id", ondelete="RESTRICT"))
    status: Mapped[str] = mapped_column(String(30))
    extractor_version: Mapped[str] = mapped_column(String(50), default="pdfplumber-layout-v2")
    original_candidates: Mapped[list] = mapped_column(JSON, default=list)
    candidates: Mapped[list] = mapped_column(JSON, default=list)
    warnings: Mapped[list] = mapped_column(JSON, default=list)
    revision: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class DocumentPage(Base):
    __tablename__ = "document_pages"
    extraction_run_id: Mapped[str] = mapped_column(ForeignKey("extraction_runs.id", ondelete="CASCADE"), primary_key=True)
    page_number: Mapped[int] = mapped_column(Integer, primary_key=True)
    text: Mapped[str] = mapped_column(Text)
    extraction_status: Mapped[str] = mapped_column(String(30))
    diagnostics: Mapped[dict] = mapped_column(JSON, default=dict, server_default="{}")
