# 윤리 임용 기출 분석 AI

## Windows에서 한 번에 실행하는 방법

1. Python **3.12 또는 3.13**을 설치합니다.
2. GitHub `main`의 최신 코드를 받습니다. 기존 설치라면 서버를 종료하고 `git pull origin main`을 실행합니다.
3. 프로젝트 루트의 **`start_windows.bat`를 더블클릭**합니다.

가상환경 생성(최초 실행), 의존성 설치, DB 마이그레이션, 서버 시작을 자동으로 수행합니다.
서버가 준비되면 브라우저가 열립니다. 주소는 `http://127.0.0.1:8000`입니다.
터미널을 켜 두고 사용하며 종료는 Ctrl+C입니다. Python 설치·패키지 다운로드 오류는 창에 표시됩니다.

## 현재 구현 범위

기본 흐름은 **PDF 업로드 → 페이지 이미지 렌더링 → 테스트 추출(Mock Provider) → 좌우 검수 → 문항 저장**입니다.

**현재 Mock은 실제 AI 문항 분리나 OCR을 하지 않습니다.** 실제 PNG 이미지와 보조 텍스트를 입력받아
페이지 전체를 임시 후보 하나로 제공합니다. 텍스트 PDF는 보조 텍스트를 표시하고, 스캔은 수동 입력 안내를
표시합니다. 문항 번호·경계·원문·지문·선택지를 사람이 확인해야 합니다. 실제 정답 분석·통계는 후속 단계입니다.

기존 Phase 1/2 CRUD, 시험 A/B 구분, 사상가·개념 정규화, 분석 버전·검수·확정본 선택,
pdfplumber 번호 분리·누락 경고를 유지합니다. 기존 추출은 화면에서 **보조/기존 추출 모드**로 선택합니다.
이전 문항과 확정 분석을 재분석하거나 덮어쓰지 않습니다.

## 브라우저 사용 순서

1. 시험을 선택하거나 생성합니다. 같은 연도의 A/B는 따로 등록합니다.
2. PDF를 선택하고 **PDF 업로드**를 누릅니다. 최대 25MB·500쪽이며 같은 SHA256은 중복 감지합니다.
3. **페이지 이미지 생성**으로 원본 페이지를 확인합니다. 모든 페이지를 144 DPI PNG로 렌더링하며
   스캔도 같은 경로를 사용합니다. 같은 문서·버전·DPI의 이미지는 재사용합니다.
4. 기본 **페이지 이미지 · 테스트 추출(Mock Provider)** 상태에서 추출 버튼을 누릅니다.
   이 단계는 필요하면 렌더링도 자동 수행합니다. 실제 AI라고 표시하지 않습니다.
5. 왼쪽 원본에서 페이지 이동·확대/축소를 하고, 오른쪽 후보에서 번호·본문·지문·선택지·답안 영역을 수정합니다.
   선택지는 일반 입력창에서 추가·삭제합니다. 관련 이미지/표와 출처 영역도 추가할 수 있습니다.
6. 문항을 선택하면 원본 출처로 이동하고 영역이 강조됩니다. **이미지에서 드래그**해 해당 페이지의
   출처 영역을 바꾸거나, 위치를 % 입력창에서 조정합니다. 내부 API는 0~1 정규화 bbox를 사용합니다.
7. 합치기·커서 분리·누락 문항 추가 후 내용·번호·출처 중복을 확인합니다.
   다음 페이지로 이어지는 문항은 합친 후 ‘다음 페이지로 이어짐’을 해제해야 저장됩니다.
8. **수정 초안 저장** 후 다시 접속해 시험·추출 이력을 선택하면 이어서 검수할 수 있습니다.
9. **검토 완료 · 문항 저장**을 누릅니다. 번호 누락은 명시적인 확인 없이 저장할 수 없고,
   기존 번호 충돌은 차단합니다. AI 분석 확정과 PDF 추출 검수는 별개의 상태입니다.

## 로컬 수동 실행 (macOS/Linux)

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.lock
.venv/bin/python -m alembic upgrade head
.venv/bin/python -m app.launcher
```

API와 UI가 같은 서버에서 제공되어 별도 Node.js/프런트엔드 서버가 필요 없습니다. `/docs`에 API 문서가 있습니다.
`127.0.0.1`은 서버를 실행한 컴퓨터에서만 열립니다. 클라우드 내부 주소가 개인 PC에 자동 공개되지는 않습니다.

## DB와 파일 저장

- `document_page_assets`: 페이지 번호, PNG 저장 키, 픽셀 크기, DPI, SHA256, 렌더링 버전.
- `page_regions`: 문항·이미지·표의 페이지 영역.
- `extraction_batches`: 입력 페이지, 이미지+보조 텍스트 해시, Provider·모델·스키마 버전, 원본 응답.
- `extraction_candidates`: 구조화된 후보와 리비전, 원본과 별개의 검수 결과.
- `candidate_sources`: 후보와 페이지 영역 연결.
- `processing_jobs`: 작업 상태·진행률·결과·오류. 기본 로컬 실행은 inline, Redis 설정 시 비동기 worker.
- `question_sources`: 기존 문서·페이지 연결 유지, 선택적 `page_region_id`와 전체 영역 참조 추가.
- 기존 `original_candidates/candidates` JSON은 유지하고 새 멀티모달 후보는 별도 테이블에도 기록합니다.
- 수정 시 이전 후보를 삭제하지 않고 비활성 이력으로 남깁니다. 문항 저장 시 지문·선택지·답안·영역을 보존합니다.

원본 PDF 캐시는 `storage/pdfs`, 로컬 객체 저장소는 `storage/assets`입니다. `PDF_STORAGE_DIR`와
`ASSET_STORAGE_DIR`로 변경할 수 있습니다. DB·PDF·페이지 이미지를 함께 백업해야 합니다.
실제 PDF·이미지 저장 폴더·DB·`.env`·개인키는 Git과 Docker build context에서 제외됩니다.
환경변수는 실행 전에 설정합니다. `.env`를 자동으로 읽거나 Git에 저장하지 않습니다.

## 새 API

| 경로 | 기능 |
|---|---|
| `/exams/{exam_id}/documents/{document_id}/render` | POST 페이지 이미지 생성 작업 |
| `/documents/{id}/page-assets` | GET 페이지 이미지 메타데이터 |
| `/page-assets/{id}/image` | GET 실제 PNG |
| `/exams/{exam_id}/documents/{document_id}/extract-images` | POST 이미지 기반 Mock 추출 작업 |
| `/processing-jobs/{id}` | GET 작업 상태·진행률·결과 |
| `/multimodal/schema` | GET Provider 출력 JSON Schema |
| `/multimodal-extractions/{id}` | GET 결과 / PUT 전체 구조화 후보 수정 |
| `/multimodal-extractions/{id}/save` | POST 검토 문항 저장 |

수정·저장은 `expected_revision`으로 충돌을 검사합니다. 입력 페이지 밖 참조, 중복 번호,
잘못된 bbox는 저장을 거부합니다. `MULTIMODAL_PROVIDER=mock` 외 Provider는 아직 연결되지 않았습니다.

기존 `/exams`, `/documents`, `/questions`, `/thinkers`, `/concepts`, `/analyses`, `/published-analyses`,
`/extractions`와 기존 pdfplumber 추출 API는 유지합니다. 새 이미지 실행은 구조화 수정·저장 API를 사용합니다.

## 테스트

```bash
.venv/bin/python -m pytest -q
.venv/bin/python -m alembic check
```

Windows는 `.venv/bin/python` 대신 `.venv\Scripts\python.exe`를 사용합니다.
테스트는 PDF를 직접 생성합니다. 실제 기출·LLM key가 필요 없습니다. Windows/Linux Python 3.12/3.13 CI를 유지합니다.
브라우저 테스트는 Chromium이 필요합니다. 로컬 브라우저 경로를 `BROWSER_EXECUTABLE`로 지정하거나
`python -m playwright install chromium` 후 `USE_PLAYWRIGHT_BROWSER=1`을 설정합니다.

외부 서비스 없는 기본 테스트에서는 Redis 통합 테스트 하나가 skipped입니다. Redis+PostgreSQL까지 검증하려면
테스트용 DB와 큐를 지정합니다. 테스트는 임의 이름의 DB 스키마와 Redis 큐를 사용하며 기존 데이터를 삭제하지 않습니다.

```bash
TEST_DATABASE_URL='postgresql+psycopg://user:password@localhost/test_db' \
TEST_REDIS_URL='redis://localhost:6379/0' .venv/bin/python -m pytest -q
```

Windows uvloop 제외 marker를 유지합니다. `pip freeze` 출력으로 lockfile 전체를 덮어쓰지 마세요.
PDF·PNG 쓰기 핸들은 읽기·이동·삭제 전에 닫아 Windows 파일 잠금을 방지합니다.

## 실제 LLM 연결을 위해 남은 작업

`app/multimodal_provider.py`의 `MultimodalExtractionProvider` 계약을 구현하고 `get_provider()`에 등록합니다.
입력은 실제 PNG bytes·페이지 번호·보조 텍스트·크기, 출력은 `ExtractionOutput`입니다.
외부 API key는 서버의 안전한 환경 설정에만 둡니다. 연결 후 이미지 기반 읽기 정확도, 인접 페이지
겹침 배치와 문항 연결, 비용·재시도·처리 제한을 실제 시험지로 검증해야 합니다.
현재 Mock은 2페이지씩 입력받지만 페이지 간 문항을 자동으로 연결하지 않습니다.

## 항상 접근 가능한 웹 배포 준비

`Dockerfile`, `render.yaml`, `deploy/production.env.example`을 제공합니다. 공개 주소는 아직 생성하지 않았습니다.
기본 배포는 **Render 상시 웹 서비스 + worker + PostgreSQL + Redis + 비공개 S3/R2 저장소**입니다.
worker에서 PDF를 처리하므로 업로드 후 브라우저가 작업 진행률을 조회합니다.

최소 사용자 작업:

1. Render 계정에서 이 GitHub 저장소의 `render.yaml`로 Blueprint를 생성하고 유료 상시 서비스를 선택합니다.
2. S3 또는 R2 비공개 버킷을 만들고 endpoint·bucket·access key·secret key를 설정합니다.
   웹과 worker에는 동일한 객체 저장소 값을 입력합니다. AWS S3가 us-east-1 밖에 있으면 OBJECT_STORAGE_REGION도 실제 지역으로 변경하고, R2는 해당 저장소의 지역 설정을 사용합니다.
3. 웹의 `ACCESS_PASSWORD`를 설정합니다. 사용자명 기본값은 `owner`입니다.
4. 배포 후 Render가 제공하는 HTTPS 주소에 접속합니다. 선택적으로 개인 도메인을 연결합니다.

Blueprint는 PostgreSQL/Redis 연결 문자열을 연결합니다. 외부 LLM key 없이도 Mock 배포가 가능합니다.
비밀값은 Render 설정에 입력하며 채팅이나 Git 파일에 넣지 않습니다. 빈 비밀번호로 production 접근하면
503, 인증 없이 접근하면 401입니다. 단일 소유자용 HTTP Basic 접근 제한이며 HTTPS로 사용해야 합니다.
사용자별 계정·권한·감사 로그가 필요한 공유 서비스는 별도 인증 시스템이 필요합니다.

직접 Docker 실행:

```bash
docker build -t ethics-review .
docker run --rm -p 8000:8000 ethics-review
```

실제 production은 `deploy/production.env.example` 항목을 비밀 환경 설정으로 전달합니다.
`OBJECT_STORAGE_BACKEND=s3`, `JOB_BACKEND=redis`를 사용해야 파일이 인스턴스 재시작 후에도 유지됩니다.
웹과 worker를 함께 실행하며 worker 명령은 `python -m app.worker`입니다. 로컬 개발 기본은 SQLite+inline+로컬 저장소입니다.
프록시 환경에서만 Docker build의 선택적 `build_ca` secret으로 신뢰할 CA를 전달할 수 있으며 TLS 검증을 끄지 않습니다.

기존 번호 경계 진단: [docs/pdf-boundaries.md](docs/pdf-boundaries.md)
