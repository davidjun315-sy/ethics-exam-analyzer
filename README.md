# 윤리 임용 기출 분석 AI

중등 윤리 임용 기출을 원문 → 분석 초안 → 사용자 검수 → 확정 데이터로 관리합니다.
현재 **Phase 1: DB와 CRUD API**를 구현했습니다. PDF 업로드·추출, 실제 LLM 호출,
검수 웹 UI, 통계 대시보드와 공부 우선순위 분석은 후속 단계입니다.

## 빠른 시작 (Python 3.12+)

```bash
cd /workspace/ethics-exam-analyzer
python -m venv .venv
.venv/bin/pip install -r requirements.lock
.venv/bin/alembic upgrade head
.venv/bin/python -m app.seed  # 선택: 실제 기출이 아닌 가상 샘플
.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000
```

기본 DB는 로컬 SQLite `ethics.db`입니다. 브라우저에서 `/docs`에 접근하면
API 입력 폼과 명세를 볼 수 있습니다. API 문서 UI이며 검수 전용 화면은 아닙니다.
환경변수는 실행 전에 export합니다. `.env` 파일을 자동으로 읽지 않습니다.

```bash
curl --fail http://127.0.0.1:8000/health
.venv/bin/pytest -q
.venv/bin/alembic check
```

## PostgreSQL

```bash
export POSTGRES_PASSWORD='개발용으로 직접 지정한 비밀번호'
docker compose up -d db
# 비밀번호의 URL 예약 문자는 URL 인코딩해야 합니다.
export DATABASE_URL='postgresql+psycopg://ethics:비밀번호@localhost:5432/ethics'
.venv/bin/alembic upgrade head
.venv/bin/python -m app.seed
.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000
```

PostgreSQL 테스트에는 별도 테스트 DB를 사용하세요. 테스트마다 임의 이름의 스키마를
만들어 격리하고 완료 후 해당 스키마만 삭제합니다. 스키마 생성 권한이 필요합니다.

```bash
TEST_DATABASE_URL='postgresql+psycopg://user:password@localhost/test_db' .venv/bin/pytest -q
```

## 주요 API

| 경로 | 기능 |
|---|---|
| `/exams`, `/documents`, `/areas`, `/thinkers`, `/concepts`, `/question-types` | POST/GET 및 `/{id}` GET/PUT/DELETE |
| `/exams/{exam_id}/documents/{document_id}` | PUT: 시험과 문서 연결 (재호출 가능) |
| `/concepts/{concept_id}/thinkers/{thinker_id}` | PUT: 개념과 사상가 연결 |
| `/questions` | POST/GET: 문항 저장, 시험·연도·원문 검색 |
| `/questions/{id}` | GET/PUT/DELETE: 분석 생성 후 원문 변경·삭제 금지 |
| `/questions/{id}/analyses` | POST/GET: 외부에서 받은 분석 초안 저장·이력 조회 |
| `/analyses/{id}/corrections` | POST: 전체 수정 내용으로 새 리비전 생성 |
| `/analyses/{id}/confirm` | POST: 분석 확정 및 현재 확정본 선택 |
| `/published-analyses` | GET: 문항별 현재 확정 분석만 조회 |
| `/review-events?analysis_id=…` | GET: 생성·수정·확정 이력 |

`exam_id` 업무 코드는 `2008_A`, 내부 연결 ID는 UUID입니다.
목록 API는 기본 50개, 최대 200개이며 `offset`/`limit`으로 페이지를 이동합니다.
PUT은 부분 수정이 아닌 전체 필드 대체입니다. 관계가 남아 있는 데이터 삭제는 409입니다.

## 검수 예시

1. `/thinkers`에 `canonical_name=이황`, `aliases=[퇴계]`를 등록합니다.
2. 시험과 문서를 등록하고 연결한 뒤 문항과 출처 페이지를 저장합니다.
3. `/questions/{id}/analyses`에 JSON을 제출합니다. `퇴계`는 `이황`으로 저장됩니다.
4. `/analyses/{id}/confirm`에 `{}`를 제출하면 첫 확정본이 됩니다.
5. 수정 시 `/corrections`에 분석 전체 필드와 `expected_revision`을 보냅니다.
6. 수정본 확정 시 `{"expected_publication_id":"이전 확정 분석 UUID"}`를 보냅니다.

수정 초안은 `unreviewed`, 원본 확정은 `confirmed`, 수정본 확정은 `corrected`입니다.
확정하려면 문제 내부 인용과 이론 근거가 모두 있어야 합니다. 문제 인용은 원문 포함 여부를
검사합니다. 이론 근거의 진실성은 자동 검증하지 않습니다.
AI 신뢰도는 0~1 범위의 참고 점수이며 정답 확률이 아닙니다.
원본 분석과 수정 이력을 덮어쓰지 않고, 현재 확정본은 문항마다 하나만 선택합니다.

## 데이터와 운영 범위

- 샘플은 `2008_SAMPLE_A/B`로 명확히 구분하며 자동 확정하지 않습니다.
- 샘플 문서는 메타데이터만 있으며 실제 PDF 파일은 없습니다.
- SQLite는 단일 개발 인스턴스용입니다. 동시 검수 운영에는 PostgreSQL을 사용합니다.
- Phase 1은 로컬 개발용이며 인증·권한·사용자별 감사 이력은 아직 없습니다.
- 공개 서비스로 배포하기 전 인증과 업로드·비용 제한을 추가해야 합니다.
- 재분석·재검수해도 현재 확정본은 명시적으로 교체할 때까지 유지됩니다.
- 의존성은 `requirements.lock`, DB 이력은 Alembic migration으로 관리합니다.

설계 및 다음 단계: [docs/roadmap.md](docs/roadmap.md)
