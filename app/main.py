import unicodedata

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from . import models as m, schemas as s
from .db import get_db

app = FastAPI(title="윤리 임용 기출 분석 AI", version="0.1.0", description="Phase 1: 원문·분석 분리와 검수 기반 데이터 API. 실제 AI 연결은 Phase 3.")


def normalize(name):
    return "".join(unicodedata.normalize("NFKC", name).casefold().split())


def get(session, model, id):
    item = session.get(model, id)
    if item is None:
        raise HTTPException(404, "데이터를 찾을 수 없습니다.")
    return item


def serialize(item):
    return {column.name: getattr(item, column.name) for column in item.__table__.columns}


def commit(session):
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        raise HTTPException(409, "중복 데이터 또는 참조 무결성 충돌입니다.")


@app.exception_handler(IntegrityError)
async def integrity_error(request, exc):
    return JSONResponse(status_code=409, content={"detail": "중복 데이터 또는 참조 무결성 충돌입니다."})


@app.get("/health")
def health(db: Session = Depends(get_db)):
    db.execute(select(m.Exam.id).limit(1))
    return {"status": "ok", "phase": 1}


def validate_parent(db, model, item_id, parent_id, field):
    visited = {item_id} if item_id else set()
    while parent_id:
        if parent_id in visited:
            raise HTTPException(422, "계층 구조에 순환 관계를 만들 수 없습니다.")
        visited.add(parent_id)
        parent = get(db, model, parent_id)
        parent_id = getattr(parent, field)


def master_aliases(db, item, model, alias_model, fk):
    db.flush()
    db.query(alias_model).filter(getattr(alias_model, fk) == item.id).delete()
    names = {normalize(name) for name in [item.canonical_name, *item.aliases]}
    for name in names:
        existing = db.get(alias_model, name)
        if existing is not None and getattr(existing, fk) != item.id:
            raise HTTPException(409, "다른 마스터에 등록된 이름 또는 별칭입니다.")
        db.add(alias_model(**{"normalized_alias": name, fk: item.id}))


def register_crud(path, model, schema):
    def list_items(offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=200), db: Session = Depends(get_db)):
        rows = db.scalars(select(model).order_by(model.id).offset(offset).limit(limit)).all()
        return [serialize(x) for x in rows]

    def read_item(id: str, db: Session = Depends(get_db)):
        return serialize(get(db, model, id))

    def save(payload, db, item=None):
        data = payload.model_dump()
        if model is m.Exam:
            data["exam_id"] = f"{data['year']}_{data['exam_part']}"
        if model is m.Area:
            validate_parent(db, model, item.id if item else None, data["parent_id"], "parent_id")
        if model is m.Concept:
            validate_parent(db, model, item.id if item else None, data["parent_concept_id"], "parent_concept_id")
        if "area_id" in data and data["area_id"]:
            get(db, m.Area, data["area_id"])
        if item:
            for key, value in data.items():
                setattr(item, key, value)
        else:
            item = model(**data)
            db.add(item)
        if model is m.Thinker:
            master_aliases(db, item, model, m.ThinkerAlias, "thinker_id")
        elif model is m.Concept:
            master_aliases(db, item, model, m.ConceptAlias, "concept_id")
        commit(db)
        return serialize(item)

    def create(payload, db: Session = Depends(get_db)):
        return save(payload, db)

    def update(id: str, payload, db: Session = Depends(get_db)):
        return save(payload, db, get(db, model, id))

    def delete(id: str, db: Session = Depends(get_db)):
        db.delete(get(db, model, id))
        commit(db)
        return {"deleted": id}

    create.__annotations__["payload"] = schema
    update.__annotations__["payload"] = schema
    app.add_api_route(path, list_items, methods=["GET"], name=f"list_{model.__tablename__}")
    app.add_api_route(path, create, methods=["POST"], status_code=201, name=f"create_{model.__tablename__}")
    app.add_api_route(path + "/{id}", read_item, methods=["GET"], name=f"get_{model.__tablename__}")
    app.add_api_route(path + "/{id}", update, methods=["PUT"], name=f"update_{model.__tablename__}")
    app.add_api_route(path + "/{id}", delete, methods=["DELETE"], name=f"delete_{model.__tablename__}")


for path, model, schema in [
    ("/exams", m.Exam, s.ExamInput), ("/documents", m.Document, s.DocumentInput),
    ("/areas", m.Area, s.AreaInput), ("/thinkers", m.Thinker, s.ThinkerInput),
    ("/concepts", m.Concept, s.ConceptInput), ("/question-types", m.QuestionType, s.TypeInput),
]:
    register_crud(path, model, schema)


@app.put("/exams/{exam_id}/documents/{document_id}")
def link_document(exam_id: str, document_id: str, db: Session = Depends(get_db)):
    get(db, m.Exam, exam_id)
    get(db, m.Document, document_id)
    key = {"exam_id": exam_id, "document_id": document_id}
    if db.get(m.ExamDocument, key) is None:
        db.add(m.ExamDocument(**key))
        commit(db)
    return key


@app.put("/concepts/{concept_id}/thinkers/{thinker_id}")
def link_thinker(concept_id: str, thinker_id: str, db: Session = Depends(get_db)):
    get(db, m.Concept, concept_id)
    get(db, m.Thinker, thinker_id)
    key = {"concept_id": concept_id, "thinker_id": thinker_id}
    if db.get(m.ConceptThinker, key) is None:
        db.add(m.ConceptThinker(**key))
        commit(db)
    return key


def question_view(db, q):
    result = serialize(q)
    result["sources"] = [serialize(x) for x in db.scalars(select(m.QuestionSource).where(m.QuestionSource.question_id == q.id))]
    publication = db.get(m.Publication, q.id)
    result["published_analysis_id"] = publication.analysis_id if publication else None
    return result


def save_question(db, payload, item=None):
    get(db, m.Exam, payload.exam_id)
    if item and db.scalar(select(m.Analysis.id).where(m.Analysis.question_id == item.id).limit(1)):
        raise HTTPException(409, "분석이 존재하는 원문은 변경할 수 없습니다. 새 문항으로 등록하세요.")
    for source in payload.sources:
        document = get(db, m.Document, source.document_id)
        if source.page_number > document.page_count:
            raise HTTPException(422, "문서 페이지 범위를 벗어났습니다.")
        if not db.get(m.ExamDocument, {"exam_id": payload.exam_id, "document_id": source.document_id}):
            raise HTTPException(422, "문서가 해당 시험에 연결되어 있지 않습니다.")
    data = payload.model_dump(exclude={"sources"})
    if item:
        for key, value in data.items():
            setattr(item, key, value)
        db.query(m.QuestionSource).filter_by(question_id=item.id).delete()
    else:
        item = m.Question(**data)
        db.add(item)
    db.flush()
    for document_id, page in {(x.document_id, x.page_number) for x in payload.sources}:
        db.add(m.QuestionSource(question_id=item.id, document_id=document_id, page_number=page))
    commit(db)
    return question_view(db, item)


@app.post("/questions", status_code=201)
def create_question(payload: s.QuestionInput, db: Session = Depends(get_db)):
    return save_question(db, payload)


@app.get("/questions")
def list_questions(exam_id: str | None = None, year: int | None = None, q: str | None = None,
                   offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=200), db: Session = Depends(get_db)):
    stmt = select(m.Question).join(m.Exam)
    if exam_id:
        stmt = stmt.where(m.Question.exam_id == exam_id)
    if year:
        stmt = stmt.where(m.Exam.year == year)
    if q:
        stmt = stmt.where(m.Question.question_text.contains(q, autoescape=True))
    return [question_view(db, row) for row in db.scalars(stmt.order_by(m.Exam.year, m.Exam.exam_part, m.Question.question_number).offset(offset).limit(limit))]


@app.get("/questions/{id}")
def read_question(id: str, db: Session = Depends(get_db)):
    return question_view(db, get(db, m.Question, id))


@app.put("/questions/{id}")
def update_question(id: str, payload: s.QuestionInput, db: Session = Depends(get_db)):
    return save_question(db, payload, get(db, m.Question, id))


@app.delete("/questions/{id}")
def delete_question(id: str, db: Session = Depends(get_db)):
    item = get(db, m.Question, id)
    if db.scalar(select(m.Analysis.id).where(m.Analysis.question_id == id).limit(1)):
        raise HTTPException(409, "분석 이력이 있는 문항은 삭제할 수 없습니다.")
    db.delete(item)
    commit(db)
    return {"deleted": id}


def resolve(db, alias_model, fk, name):
    item = db.get(alias_model, normalize(name))
    if not item:
        raise HTTPException(422, f"미등록 명칭입니다. 마스터를 먼저 등록하세요: {name}")
    return getattr(item, fk)


def analysis_view(db, item):
    result = serialize(item)
    for role, label in [("primary", "primary_thinkers"), ("related", "related_thinkers")]:
        result[label] = list(db.scalars(select(m.Thinker.canonical_name).join(m.AnalysisThinker).where(m.AnalysisThinker.analysis_id == item.id, m.AnalysisThinker.role == role)))
    for role, label in [("primary", "primary_concept"), ("sub", "sub_concepts")]:
        names = list(db.scalars(select(m.Concept.canonical_name).join(m.AnalysisConcept).where(m.AnalysisConcept.analysis_id == item.id, m.AnalysisConcept.role == role)))
        result[label] = (names[0] if names else None) if role == "primary" else names
    result["question_types"] = list(db.scalars(select(m.QuestionType.name).join(m.AnalysisType).where(m.AnalysisType.analysis_id == item.id)))
    result["evidence"] = [serialize(x) for x in db.scalars(select(m.Evidence).where(m.Evidence.analysis_id == item.id))]
    return result


def create_analysis_record(db, question_id, payload, parent=None):
    get(db, m.Question, question_id)
    # Serialize revision allocation and publication on PostgreSQL; SQLite relies on unique constraints.
    db.execute(select(m.Question).where(m.Question.id == question_id).with_for_update())
    latest = db.scalar(select(func.max(m.Analysis.revision_number)).where(m.Analysis.question_id == question_id)) or 0
    if parent and (payload.expected_revision != parent.revision_number or latest != parent.revision_number):
        raise HTTPException(409, "최신 분석이 변경되었습니다. 다시 조회하세요.")
    data = payload.model_dump(exclude={"primary_thinkers", "related_thinkers", "primary_concept", "sub_concepts", "question_types", "evidence", "expected_revision"})
    for field in ["area_id", "sub_area_id"]:
        if data[field]:
            get(db, m.Area, data[field])
    item = m.Analysis(**data, question_id=question_id, revision_number=latest + 1,
                      origin="human" if parent else "ai", parent_analysis_id=parent.id if parent else None)
    db.add(item)
    db.flush()
    thinkers = {}
    for role, names in [("primary", payload.primary_thinkers), ("related", payload.related_thinkers)]:
        for name in names:
            id = resolve(db, m.ThinkerAlias, "thinker_id", name)
            if id in thinkers and thinkers[id] != role:
                raise HTTPException(422, "동일 사상가를 주요·관련 역할에 동시에 지정할 수 없습니다.")
            thinkers[id] = role
    for id, role in thinkers.items():
        db.add(m.AnalysisThinker(analysis_id=item.id, thinker_id=id, role=role))
    concepts = {}
    for role, names in [("primary", [payload.primary_concept] if payload.primary_concept else []), ("sub", payload.sub_concepts)]:
        for name in names:
            id = resolve(db, m.ConceptAlias, "concept_id", name)
            if id in concepts and concepts[id] != role:
                raise HTTPException(422, "동일 개념을 핵심·세부 역할에 동시에 지정할 수 없습니다.")
            concepts[id] = role
    for id, role in concepts.items():
        db.add(m.AnalysisConcept(analysis_id=item.id, concept_id=id, role=role))
    for name in set(payload.question_types):
        type_id = db.scalar(select(m.QuestionType.id).where(m.QuestionType.name == name))
        if not type_id:
            raise HTTPException(422, f"미등록 문제 유형: {name}")
        db.add(m.AnalysisType(analysis_id=item.id, question_type_id=type_id))
    for evidence in payload.evidence:
        if evidence.kind == "question":
            original = get(db, m.Question, question_id).raw_text
            if normalize(evidence.text) not in normalize(original):
                raise HTTPException(422, "문제 내부 근거는 원문에 존재하는 인용이어야 합니다.")
        db.add(m.Evidence(analysis_id=item.id, **evidence.model_dump()))
    db.add(m.ReviewEvent(analysis_id=item.id, action="draft_corrected" if parent else "analysis_created"))
    commit(db)
    return analysis_view(db, item)


@app.post("/questions/{question_id}/analyses", status_code=201)
def create_analysis(question_id: str, payload: s.AnalysisInput, db: Session = Depends(get_db)):
    return create_analysis_record(db, question_id, payload)


@app.get("/questions/{question_id}/analyses")
def list_analyses(question_id: str, db: Session = Depends(get_db)):
    get(db, m.Question, question_id)
    return [analysis_view(db, x) for x in db.scalars(select(m.Analysis).where(m.Analysis.question_id == question_id).order_by(m.Analysis.revision_number))]


@app.get("/analyses/{id}")
def read_analysis(id: str, db: Session = Depends(get_db)):
    return analysis_view(db, get(db, m.Analysis, id))


@app.post("/analyses/{id}/corrections", status_code=201)
def correct_analysis(id: str, payload: s.CorrectionInput, db: Session = Depends(get_db)):
    parent = get(db, m.Analysis, id)
    return create_analysis_record(db, parent.question_id, payload, parent)


@app.post("/analyses/{id}/confirm")
def confirm_analysis(id: str, payload: s.PublishInput, db: Session = Depends(get_db)):
    item = get(db, m.Analysis, id)
    db.execute(select(m.Question).where(m.Question.id == item.question_id).with_for_update())
    publication = db.get(m.Publication, item.question_id)
    current = publication.analysis_id if publication else None
    if current != payload.expected_publication_id:
        raise HTTPException(409, "확정본이 변경되었습니다. 현재 확정본을 확인하세요.")
    evidence_kinds = set(db.scalars(select(m.Evidence.kind).where(m.Evidence.analysis_id == id)))
    if evidence_kinds != {"question", "theory"}:
        raise HTTPException(422, "확정하려면 문제 내부 근거와 이론 근거가 모두 필요합니다.")
    item.review_status = "corrected" if item.origin == "human" else "confirmed"
    if publication:
        publication.analysis_id = item.id
        publication.published_at = m.now()
    else:
        db.add(m.Publication(question_id=item.question_id, analysis_id=item.id))
    db.add(m.ReviewEvent(analysis_id=item.id, action=item.review_status))
    commit(db)
    return analysis_view(db, item)


@app.get("/review-events")
def review_events(analysis_id: str, db: Session = Depends(get_db)):
    get(db, m.Analysis, analysis_id)
    return [serialize(x) for x in db.scalars(select(m.ReviewEvent).where(m.ReviewEvent.analysis_id == analysis_id).order_by(m.ReviewEvent.created_at))]


@app.get("/published-analyses")
def published_analyses(db: Session = Depends(get_db)):
    rows = db.scalars(select(m.Analysis).join(m.Publication, m.Publication.analysis_id == m.Analysis.id)
                      .where(m.Analysis.review_status.in_(["confirmed", "corrected"])))
    return [analysis_view(db, x) for x in rows]
