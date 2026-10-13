import hashlib
import io
import json
import threading

import pdfplumber
import pypdfium2 as pdfium
from fastapi import APIRouter, Depends, HTTPException, Response
from fastapi.encoders import jsonable_encoder
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import models as m, schemas as s
from .db import get_db
from .blob_storage import object_storage
from .multimodal_provider import PageInput, ExtractionOutput, get_provider
from .extraction import missing_numbers, gap_warnings
from .pdf_api import storage, helpers, locked_run, Save

router = APIRouter()
RENDER_VERSION = 'pdfium-png-v1'
DPI = 144
PDFIUM_LOCK = threading.Lock()


def check_document(db, exam_id, document_id):
    _, get, _ = helpers()
    doc = get(db, m.Document, document_id)
    if not db.get(m.ExamDocument, {'exam_id': exam_id, 'document_id': document_id}):
        raise HTTPException(422, '시험에 연결되지 않은 문서입니다.')
    return doc


def pdf_path(doc):
    path = storage() / f'{doc.sha256}.pdf'
    if not path.exists():
        blobs = object_storage()
        key = f'pdfs/{doc.sha256}.pdf'
        if not blobs.exists(key):
            raise HTTPException(409, 'PDF 원본을 다시 업로드하세요.')
        # Same Windows-safe atomic writer used by the local object store.
        from .blob_storage import LocalObjectStorage
        local = LocalObjectStorage()
        local.root = storage()
        data = blobs.read(key)
        if hashlib.sha256(data).hexdigest() != doc.sha256:
            raise HTTPException(409, 'PDF 원본 SHA256 검증에 실패했습니다.')
        local.put(f'{doc.sha256}.pdf', data, 'application/pdf')
    return path


def assets(db, document_id):
    return db.scalars(select(m.PageAsset).where(m.PageAsset.document_id == document_id,
                        m.PageAsset.render_version == RENDER_VERSION, m.PageAsset.dpi == DPI)
                      .order_by(m.PageAsset.page_number)).all()


def asset_view(asset):
    _, _, serialize = helpers()
    return {**serialize(asset), 'image_url': f'/page-assets/{asset.id}/image'}


def render_document(db, doc, job=None):
    blobs = object_storage()
    result = []
    # PDFium is not thread-safe. Close bitmap, PIL image, page and document handles.
    with PDFIUM_LOCK:
        existing = {a.page_number: a for a in assets(db, doc.id)}
        pdf = pdfium.PdfDocument(str(pdf_path(doc)))
        try:
            for index in range(len(pdf)):
                n = index + 1
                if n in existing and blobs.exists(existing[n].storage_key):
                    result.append(existing[n])
                else:
                    page = pdf[index]
                    try:
                        w, h = page.get_size()
                        if w * h * (DPI / 72) ** 2 > 20_000_000:
                            raise HTTPException(422, '페이지 이미지가 너무 큽니다. 일반 용지 크기 PDF를 사용하세요.')
                        bitmap = page.render(scale=DPI / 72)
                        try:
                            image = bitmap.to_pil()
                            try:
                                output = io.BytesIO()
                                image.save(output, format='PNG')
                                width, height = image.size
                            finally:
                                image.close()
                        finally:
                            bitmap.close()
                    finally:
                        page.close()
                    data = output.getvalue()
                    key = f'pages/{doc.sha256}/{RENDER_VERSION}/{DPI}/{n}.png'
                    blobs.put(key, data, 'image/png')
                    asset = existing.get(n) or m.PageAsset(document_id=doc.id, page_number=n, dpi=DPI, render_version=RENDER_VERSION)
                    asset.storage_key, asset.width_px, asset.height_px = key, width, height
                    asset.sha256 = hashlib.sha256(data).hexdigest()
                    db.add(asset)
                    db.flush()
                    result.append(asset)
                if job:
                    job.progress = int(n / len(pdf) * 90)
                    db.commit()
        finally:
            pdf.close()
    return result


def auxiliary_text(doc):
    # Text is optional. Image rendering/extraction must work when this fails.
    try:
        with pdfplumber.open(pdf_path(doc)) as pdf:
            return {i: page.extract_text() or '' for i, page in enumerate(pdf.pages, 1)}
    except Exception:
        return {}


def persist_candidates(db, run, payload, parents=None):
    old = db.scalars(select(m.ExtractionCandidate).where(m.ExtractionCandidate.extraction_run_id == run.id,
                                                       m.ExtractionCandidate.active.is_(True))).all()
    for candidate in old:
        candidate.active = False
    page_assets = {a.page_number: a for a in assets(db, run.document_id)}
    for question in payload.questions:
        # Validate page references before creating any candidate or region.
        if any(source.page_number not in page_assets for source in [*question.sources, *question.visual_elements]):
            raise HTTPException(422, '출처 페이지가 문서에 없습니다.')
    numbers = [q.question_number for q in payload.questions]
    if len(numbers) != len(set(numbers)):
        raise HTTPException(422, '문항 번호가 중복되었습니다.')
    for question in payload.questions:
        candidate = m.ExtractionCandidate(extraction_run_id=run.id, question_number=question.question_number,
            payload=question.model_dump(), revision=run.revision, parent_candidate_ids=parents or [c.id for c in old if {source.page_number for source in question.sources} & {source['page_number'] for source in c.payload['sources']}])
        db.add(candidate)
        db.flush()
        for role, sources in [('source', question.sources), ('visual', question.visual_elements)]:
            for source in sources:
                region = m.PageRegion(page_asset_id=page_assets[source.page_number].id, extraction_run_id=run.id,
                                      region_type=getattr(source, 'type', 'question'), bbox=source.bbox)
                db.add(region)
                db.flush()
                db.add(m.CandidateSource(candidate_id=candidate.id, page_region_id=region.id, role=role))
    # Legacy JSON is retained for history/API compatibility; structured rows are canonical for vision runs.
    run.candidates = [{**q.model_dump(), 'text': q.question_text,
                       'pages': sorted({source.page_number for source in q.sources}), 'source_indexes': [i]}
                      for i, q in enumerate(payload.questions)]


def vision_view(db, run):
    _, _, serialize = helpers()
    candidates = db.scalars(select(m.ExtractionCandidate).where(m.ExtractionCandidate.extraction_run_id == run.id,
                          m.ExtractionCandidate.active.is_(True)).order_by(m.ExtractionCandidate.question_number)).all()
    return {**serialize(run), 'provider_label': '테스트 추출(Mock Provider)',
            'structured_candidates': [{**c.payload, 'id': c.id, 'revision': c.revision, 'review_status': c.review_status} for c in candidates],
            'missing_numbers': missing_numbers(run.candidates),
            'warnings': run.warnings + gap_warnings(run.candidates),
            'page_assets': [asset_view(a) for a in assets(db, run.document_id)]}


def extract_images(db, doc, exam_id, job=None):
    page_assets = render_document(db, doc, job)
    texts = auxiliary_text(doc)
    provider = get_provider()
    blobs = object_storage()
    run = m.ExtractionRun(document_id=doc.id, exam_id=exam_id, status='extracted', engine='multimodal',
                         extractor_version='multimodal-schema-v1', warnings=['테스트 추출(Mock Provider): 페이지별 임시 후보입니다. 실제 AI 문항 분리·OCR 결과가 아닙니다.'])
    db.add(run)
    db.flush()
    questions = []
    # Bounded image batches. Real providers can use overlapping context; the mock is page-based.
    for start in range(0, len(page_assets), 2):
        inputs = [PageInput(a.page_number, blobs.read(a.storage_key), texts.get(a.page_number, ''), a.width_px, a.height_px)
                  for a in page_assets[start:start+2]]
        response = provider.extract(inputs)
        raw = response.model_dump() if isinstance(response, ExtractionOutput) else response
        validated = ExtractionOutput.model_validate(raw)
        batch_pages = {page.page_number for page in inputs}
        if any(source.page_number not in batch_pages for q in validated.questions for source in [*q.sources, *q.visual_elements]):
            raise HTTPException(422, 'Provider가 입력 배치 밖 페이지를 참조했습니다.')
        digest = hashlib.sha256()
        for page in inputs:
            digest.update(page.image_png)
            digest.update(page.auxiliary_text.encode())
        db.add(m.ExtractionBatch(extraction_run_id=run.id, page_numbers=sorted(batch_pages), input_hash=digest.hexdigest(),
                                provider=provider.name, model=provider.model, prompt_version='mock-v1', schema_version='vision-v1',
                                raw_response=raw, status='validated'))
        questions.extend(validated.questions)
    output = ExtractionOutput(questions=questions)
    persist_candidates(db, run, output)
    run.original_candidates = run.candidates
    for a in page_assets:
        db.add(m.DocumentPage(extraction_run_id=run.id, page_number=a.page_number, text=texts.get(a.page_number, ''),
                             extraction_status='auxiliary_text' if texts.get(a.page_number) else 'image_only', diagnostics={}))
    return run


def execute_job(db, job):
    commit, get, _ = helpers()
    job.status = 'running'
    commit(db)
    try:
        doc = get(db, m.Document, job.document_id)
        if job.kind == 'render':
            result = {'page_assets': [asset_view(a) for a in render_document(db, doc, job)]}
        else:
            run = extract_images(db, doc, job.exam_id, job)
            result = {'extraction_run_id': run.id}
        job.status, job.progress, job.result = 'completed', 100, jsonable_encoder(result)
        commit(db)
    except Exception:
        db.rollback()
        job = get(db, m.ProcessingJob, job.id)
        job.status, job.error = 'failed', '처리에 실패했습니다. 원본 파일·저장소·Provider 설정을 확인하고 다시 실행하세요.'
        commit(db)
        raise
    return job


def start_job(db, exam_id, document_id, kind):
    commit, _, serialize = helpers()
    check_document(db, exam_id, document_id)
    job = m.ProcessingJob(exam_id=exam_id, document_id=document_id, kind=kind)
    db.add(job)
    commit(db)
    from .jobs import dispatch
    dispatch(db, job)
    return serialize(job)


@router.post('/exams/{exam_id}/documents/{document_id}/render', status_code=201)
def render(exam_id: str, document_id: str, db: Session = Depends(get_db)):
    return start_job(db, exam_id, document_id, 'render')


@router.post('/exams/{exam_id}/documents/{document_id}/extract-images', status_code=201)
def image_extract(exam_id: str, document_id: str, db: Session = Depends(get_db)):
    return start_job(db, exam_id, document_id, 'multimodal')


@router.get('/processing-jobs/{id}')
def job_status(id: str, db: Session = Depends(get_db)):
    _, get, serialize = helpers()
    return serialize(get(db, m.ProcessingJob, id))


@router.get('/documents/{id}/page-assets')
def list_assets(id: str, db: Session = Depends(get_db)):
    _, get, _ = helpers()
    get(db, m.Document, id)
    return [asset_view(a) for a in assets(db, id)]


@router.get('/page-assets/{id}/image')
def page_image(id: str, db: Session = Depends(get_db)):
    _, get, _ = helpers()
    asset = get(db, m.PageAsset, id)
    blobs = object_storage()
    if not blobs.exists(asset.storage_key):
        raise HTTPException(404, '페이지 이미지가 없습니다. 다시 렌더링하세요.')
    data = blobs.read(asset.storage_key)
    if hashlib.sha256(data).hexdigest() != asset.sha256:
        raise HTTPException(409, '페이지 이미지 SHA256 검증에 실패했습니다.')
    return Response(data, media_type='image/png', headers={'Cache-Control': 'private, max-age=3600'})


@router.get('/multimodal/schema')
def schema():
    return ExtractionOutput.model_json_schema()


@router.get('/multimodal-extractions/{id}')
def read_vision(id: str, db: Session = Depends(get_db)):
    _, get, _ = helpers()
    run = get(db, m.ExtractionRun, id)
    if run.engine != 'multimodal':
        raise HTTPException(422, '기존 추출 API를 사용하세요.')
    return vision_view(db, run)


class VisionEdit(s.Input):
    expected_revision: int
    output: ExtractionOutput


@router.put('/multimodal-extractions/{id}')
def edit_vision(id: str, payload: VisionEdit, db: Session = Depends(get_db)):
    commit, _, _ = helpers()
    run = locked_run(db, id, payload.expected_revision)
    if run.engine != 'multimodal':
        raise HTTPException(422, '기존 추출 API를 사용하세요.')
    run.revision += 1
    persist_candidates(db, run, payload.output)
    commit(db)
    return vision_view(db, run)


@router.post('/multimodal-extractions/{id}/save')
def save_vision(id: str, payload: Save, db: Session = Depends(get_db)):
    commit, _, _ = helpers()
    run = locked_run(db, id, payload.expected_revision)
    if run.engine != 'multimodal':
        raise HTTPException(422, '기존 추출 API를 사용하세요.')
    if missing_numbers(run.candidates) and not payload.acknowledge_missing:
        raise HTTPException(422, '번호 누락 경고를 확인하세요.')
    candidates = db.scalars(select(m.ExtractionCandidate).where(m.ExtractionCandidate.extraction_run_id == id, m.ExtractionCandidate.active.is_(True))).all()
    db.execute(select(m.Exam).where(m.Exam.id == run.exam_id).with_for_update())
    if db.scalar(select(m.Question.id).where(m.Question.exam_id == run.exam_id,
                 m.Question.question_number.in_([c.question_number for c in candidates])).limit(1)):
        raise HTTPException(409, '기존 문항 번호와 충돌합니다. 기존 문항은 덮어쓰지 않습니다.')
    ids = []
    for candidate in candidates:
        q = candidate.payload
        source_pages = {source['page_number'] for source in q['sources']}
        original = json.dumps([c for c in run.original_candidates if source_pages & {source['page_number'] for source in c['sources']}], ensure_ascii=False)
        if q['continues_to_next_page']:
            raise HTTPException(422, '다음 페이지로 이어지는 문항을 먼저 합치고 이어짐 표시를 해제하세요.')
        question = m.Question(exam_id=run.exam_id, question_number=q['question_number'], question_text=q['question_text'],
                              passage=q['passage'], choices=q['choices'], answer_area=q['answer_area'], raw_text=original)
        db.add(question)
        db.flush()
        regions = db.execute(select(m.CandidateSource, m.PageRegion, m.PageAsset)
                    .join(m.PageRegion, m.CandidateSource.page_region_id == m.PageRegion.id)
                    .join(m.PageAsset, m.PageRegion.page_asset_id == m.PageAsset.id)
                    .where(m.CandidateSource.candidate_id == candidate.id)).all()
        grouped = {}
        for link, region, asset in regions:
            grouped.setdefault(asset.page_number, []).append({'page_region_id': region.id, 'bbox': region.bbox, 'type': region.region_type, 'role': link.role})
        for page_number, refs in grouped.items():
            db.add(m.QuestionSource(question_id=question.id, document_id=run.document_id, page_number=page_number,
                                    page_region_id=refs[0]['page_region_id'], regions=refs))
        candidate.review_status, candidate.saved_question_id = 'reviewed', question.id
        ids.append(question.id)
    run.status, run.revision = 'saved', run.revision + 1
    commit(db)
    return {'question_ids': ids, 'run': vision_view(db, run)}
