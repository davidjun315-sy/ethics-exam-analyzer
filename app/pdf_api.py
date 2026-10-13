import hashlib
import os
from pathlib import Path
from tempfile import NamedTemporaryFile

import pdfplumber
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import models as m, schemas as s
from .db import get_db
from .extraction import VERSION, analyze_page, split_questions, missing_numbers, gap_warnings

router = APIRouter()
MAX_BYTES = 25 * 1024 * 1024


def storage():
    path = Path(os.getenv('PDF_STORAGE_DIR', 'storage/pdfs')).resolve()
    path.mkdir(parents=True, exist_ok=True)
    return path


def helpers():
    from .main import commit, get, serialize
    return commit, get, serialize


@router.post('/exams/{exam_id}/upload', status_code=201)
def upload(exam_id: str, file: UploadFile = File(...), db: Session = Depends(get_db)):
    commit, get, serialize = helpers()
    temporary = None
    try:
        get(db, m.Exam, exam_id)
        filename = Path((file.filename or 'upload.pdf').replace('\\', '/')).name
        if not filename.lower().endswith('.pdf') or len(filename) > 255:
            raise HTTPException(422, 'PDF 파일을 선택해 주세요. 파일명은 255자 이하여야 합니다.')
        digest, size = hashlib.sha256(), 0
        # Windows forbids replacing/deleting an open NamedTemporaryFile.
        # Close the writer BEFORE opening the PDF, promoting it, or cleaning up.
        with NamedTemporaryFile(dir=storage(), suffix='.tmp', delete=False) as tmp:
            temporary = Path(tmp.name)
            while chunk := file.file.read(1024 * 1024):
                size += len(chunk)
                if size > MAX_BYTES:
                    raise HTTPException(413, 'PDF 최대 크기는 25MB입니다.')
                digest.update(chunk)
                tmp.write(chunk)
        with temporary.open('rb') as stream:
            if stream.read(5) != b'%PDF-':
                raise HTTPException(422, '유효한 PDF 파일이 아닙니다.')
        try:
            with pdfplumber.open(temporary) as pdf:
                count = len(pdf.pages)
                if not 1 <= count <= 500:
                    raise HTTPException(422, 'PDF는 1~500쪽이어야 합니다.')
        except HTTPException:
            raise
        except Exception:
            raise HTTPException(422, 'PDF를 읽을 수 없습니다. 손상되었거나 암호화된 파일인지 확인해 주세요.')
        sha = digest.hexdigest()
        existing = db.scalar(select(m.Document).where(m.Document.sha256 == sha).order_by(m.Document.uploaded_at))
        duplicate = existing is not None
        doc = existing or m.Document(filename=filename, storage_key=f'{sha}.pdf', sha256=sha, page_count=count)
        # Hash-derived path prevents filename traversal; repair missing original on duplicate upload.
        destination = storage() / f'{sha}.pdf'
        if not destination.exists():
            temporary.replace(destination)
        from .blob_storage import object_storage
        object_storage().put(f'pdfs/{sha}.pdf', destination.read_bytes(), 'application/pdf')
        if not existing:
            db.add(doc)
            db.flush()
        if db.get(m.ExamDocument, {'exam_id': exam_id, 'document_id': doc.id}) is None:
            db.add(m.ExamDocument(exam_id=exam_id, document_id=doc.id))
        commit(db)
        return {'document': serialize(doc), 'duplicate': duplicate}
    finally:
        try:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
        finally:
            file.file.close()


@router.get('/exams/{exam_id}/uploaded-documents')
def uploaded_documents(exam_id: str, db: Session = Depends(get_db)):
    _, get, serialize = helpers()
    get(db, m.Exam, exam_id)
    docs = db.scalars(select(m.Document).join(m.ExamDocument).where(m.ExamDocument.exam_id == exam_id))
    return [serialize(x) for x in docs]


class ExtractOptions(s.Input):
    column_mode: s.Literal['auto', 'single', 'two'] = 'auto'
    allow_circled: bool = False


@router.post('/exams/{exam_id}/documents/{document_id}/extract', status_code=201)
def extract(exam_id: str, document_id: str, options: ExtractOptions = ExtractOptions(), db: Session = Depends(get_db)):
    commit, get, serialize = helpers()
    doc = get(db, m.Document, document_id)
    if not db.get(m.ExamDocument, {'exam_id': exam_id, 'document_id': document_id}):
        raise HTTPException(422, '시험에 연결되지 않은 문서입니다.')
    # Never trust the metadata-only storage_key supplied by Phase 1 CRUD.
    from .multimodal_api import pdf_path
    path = pdf_path(doc)
    pages, warnings, layouts = [], [], {}
    try:
        with pdfplumber.open(path) as pdf:
            for i, page in enumerate(pdf.pages, 1):
                layout = analyze_page(page, options.column_mode, options.allow_circled)
                layouts[i] = layout
                pages.append((i, layout['text']))
                if layout['two_columns']:
                    warnings.append(f'{i}쪽: 2단 편집을 감지해 왼쪽→오른쪽 순서로 추출했습니다. 경계를 확인해 주세요.')
    except Exception:
        raise HTTPException(422, 'PDF 텍스트 추출에 실패했습니다.')
    original, boundary_warnings = split_questions(pages, layouts, options.allow_circled)
    empty = [i for i, text in pages if not text.strip()]
    warnings += boundary_warnings
    if empty:
        warnings.append(f'텍스트가 없는 페이지: {empty}. OCR 또는 수동 입력이 필요합니다.')
    status = 'needs_ocr' if len(empty) == len(pages) else ('partial' if empty else 'extracted')
    run = m.ExtractionRun(document_id=document_id, exam_id=exam_id, status=status,
                          original_candidates=original, candidates=original, warnings=warnings, extractor_version=VERSION)
    db.add(run)
    db.flush()
    for i, text in pages:
        db.add(m.DocumentPage(extraction_run_id=run.id, page_number=i, text=text,
                             extraction_status='extracted' if text.strip() else 'needs_ocr', diagnostics=layouts[i]))
    commit(db)
    return run_view(db, run)


def run_view(db, run):
    _, _, serialize = helpers()
    if run.engine == 'multimodal':
        from .multimodal_api import vision_view
        return vision_view(db, run)
    result = serialize(run)
    result['missing_numbers'] = missing_numbers(run.candidates)
    result['warnings'] = [w for w in run.warnings if '번 문항 경계 누락 가능성:' not in w] + gap_warnings(run.candidates)
    result['pages'] = [serialize(x) for x in db.scalars(select(m.DocumentPage).where(m.DocumentPage.extraction_run_id == run.id).order_by(m.DocumentPage.page_number))]
    report = []
    for n in result['missing_numbers']:
        evidence = [{**line, 'page_number': page['page_number']} for page in result['pages']
                    for line in page.get('diagnostics', {}).get('lines', []) if line.get('number') == n]
        native_pages = [page['page_number'] for page in result['pages']
                        if n in page.get('diagnostics', {}).get('native_number_order', [])]
        if any(line['accepted'] for line in evidence):
            cause = '번호 좌표 후보는 있으나 중복·역순 때문에 경계에서 제외됨: 읽기 순서 또는 내부 번호 확인 필요'
        elif evidence:
            cause = '텍스트 번호 후보는 있으나 좌표 조건에서 제외됨: ' + ', '.join(sorted({line['reason'] for line in evidence}))
        elif native_pages:
            cause = '기본 추출 텍스트에는 번호가 있으나 좌표 정렬에서 확인되지 않음: 토큰·줄 배치 확인 필요'
        else:
            cause = '추출 텍스트에서 번호 후보를 확인하지 못함: 이미지 번호·문자 매핑·텍스트 누락 여부를 원본 PDF와 비교해야 함'
        report.append({'question_number': n, 'cause': cause, 'evidence': evidence, 'native_pages': native_pages})
    result['boundary_report'] = report
    return result


@router.get('/exams/{exam_id}/extractions')
def list_runs(exam_id: str, db: Session = Depends(get_db)):
    _, get, serialize = helpers()
    get(db, m.Exam, exam_id)
    return [serialize(x) for x in db.scalars(select(m.ExtractionRun).where(m.ExtractionRun.exam_id == exam_id).order_by(m.ExtractionRun.created_at.desc()))]


@router.get('/extractions/{id}')
def read_run(id: str, db: Session = Depends(get_db)):
    _, get, _ = helpers()
    return run_view(db, get(db, m.ExtractionRun, id))


class Candidate(s.Input):
    question_number: int = Field(gt=0)
    text: s.Text
    pages: list[int] = Field(min_length=1)
    source_indexes: list[int] = Field(min_length=1)


class Edit(s.Input):
    expected_revision: int = Field(gt=0)
    candidates: list[Candidate] = Field(min_length=1, max_length=500)


class Save(s.Input):
    expected_revision: int = Field(gt=0)
    acknowledge_missing: bool = False


def locked_run(db, id, revision):
    run = db.scalar(select(m.ExtractionRun).where(m.ExtractionRun.id == id).with_for_update())
    if run is None:
        raise HTTPException(404, '추출 결과가 없습니다.')
    if run.status == 'saved':
        raise HTTPException(409, '이미 문항으로 저장된 결과입니다. 새 추출 또는 문항 API를 사용하세요.')
    if run.revision != revision:
        raise HTTPException(409, '다른 화면에서 수정되었습니다. 새로 조회해 주세요.')
    return run


@router.put('/extractions/{id}')
def edit_run(id: str, payload: Edit, db: Session = Depends(get_db)):
    commit, _, _ = helpers()
    run = locked_run(db, id, payload.expected_revision)
    if run.engine == 'multimodal':
        raise HTTPException(422, '멀티모달 수정 API를 사용하세요.')
    nums = [x.question_number for x in payload.candidates]
    if len(nums) != len(set(nums)):
        raise HTTPException(422, '문항 번호가 중복되었습니다.')
    for candidate in payload.candidates:
        if any(i < 0 or i >= len(run.original_candidates) for i in candidate.source_indexes):
            raise HTTPException(422, '원본 후보 참조가 잘못되었습니다.')
        possible = {p for i in candidate.source_indexes for p in run.original_candidates[i]['pages']}
        if not set(candidate.pages) <= possible or any(p < 1 for p in candidate.pages):
            raise HTTPException(422, '출처 페이지가 원본 범위를 벗어났습니다.')
    run.candidates = [x.model_dump() for x in payload.candidates]
    run.revision += 1
    commit(db)
    return run_view(db, run)


@router.post('/extractions/{id}/save')
def save_run(id: str, payload: Save, db: Session = Depends(get_db)):
    commit, _, _ = helpers()
    run = locked_run(db, id, payload.expected_revision)
    if run.engine == 'multimodal':
        raise HTTPException(422, '멀티모달 저장 API를 사용하세요.')
    if not run.candidates:
        raise HTTPException(422, '저장할 문항이 없습니다. 스캔 문서는 OCR이 필요합니다.')
    if missing_numbers(run.candidates) and not payload.acknowledge_missing:
        raise HTTPException(422, '누락 가능 문항이 있습니다. 보정하거나 번호 누락 경고를 확인한 뒤 저장해 주세요.')
    # Lock the exam to serialize overlapping imports on PostgreSQL.
    db.execute(select(m.Exam).where(m.Exam.id == run.exam_id).with_for_update())
    numbers = [x['question_number'] for x in run.candidates]
    if db.scalar(select(m.Question.id).where(m.Question.exam_id == run.exam_id, m.Question.question_number.in_(numbers)).limit(1)):
        raise HTTPException(409, '시험에 같은 번호의 문항이 이미 있습니다. 후보 번호를 수정하세요. 기존 문항은 덮어쓰지 않습니다.')
    ids = []
    for candidate in run.candidates:
        raw = '\n'.join(run.original_candidates[i]['text'] for i in sorted(set(candidate['source_indexes'])))
        q = m.Question(exam_id=run.exam_id, question_number=candidate['question_number'], question_text=candidate['text'], raw_text=raw)
        db.add(q)
        db.flush()
        ids.append(q.id)
        for page in sorted(set(candidate['pages'])):
            db.add(m.QuestionSource(question_id=q.id, document_id=run.document_id, page_number=page))
    run.status = 'saved'
    run.revision += 1
    commit(db)
    return {'question_ids': ids, 'run': run_view(db, run)}
