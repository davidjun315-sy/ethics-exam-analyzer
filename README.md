# 윤리 임용 기출 분석 AI

윤리 임용 기출을 **PDF → 문항 추출 → 사용자 검수 → 문항 DB**로 관리하는 개발 버전입니다.
Phase 1 DB·CRUD API 위에 Phase 2 PDF 처리와 브라우저 검수 화면을 추가했습니다.
실제 AI 정답 분석·OCR·통계는 아직 구현하지 않았습니다.

## 브라우저에서 사용하는 방법

웹 UI와 API는 **하나의 FastAPI 서버**에서 실행됩니다. 별도의 프런트엔드 서버나 Node.js 설치는 필요 없습니다.

공식 지원 대상은 Windows 11과 Linux의 Python 3.12/3.13입니다. macOS 실행 명령도 제공합니다.
Windows/Linux 설치·마이그레이션·PDF 처리·브라우저 흐름은 GitHub Actions에서 지속 검증합니다.

Python 3.12 또는 3.13을 설치한 PC의 터미널에서:

```bash
git clone https://github.com/davidjun315-sy/ethics-exam-analyzer.git
cd ethics-exam-analyzer
python -m venv .venv
```

macOS/Linux:

```bash
.venv/bin/python -m pip install -r requirements.lock
.venv/bin/alembic upgrade head
.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Windows PowerShell:

```powershell
.venv\Scripts\python.exe -m pip install -r requirements.lock
.venv\Scripts\alembic.exe upgrade head
.venv\Scripts\uvicorn.exe app.main:app --host 127.0.0.1 --port 8000
```

브라우저 주소창에 `http://127.0.0.1:8000`을 입력합니다. 터미널은 켜 둡니다.
API 문서는 `/docs`입니다. 종료는 터미널에서 Ctrl+C를 누릅니다.

이 주소는 **서버를 실행한 컴퓨터에서만** 접근할 수 있습니다. 클라우드 내부에서 실행한
서버가 개인 PC의 브라우저에 자동 공개되지는 않습니다. 이 저장소는 공개 호스팅을 제공하지 않습니다.

이미 설치한 경우에는 `git pull origin main` 후 의존성 설치와 `alembic upgrade head`를 다시 실행합니다.
기존 DB를 삭제할 필요가 없습니다. 기본 DB는 현재 폴더의 `ethics.db`입니다.

### 화면에서 PDF 처리하기

1. **시험 선택**에서 기존 시험을 고르거나 **새 시험 만들기**를 엽니다. 연도·구분·이름을 입력합니다. 예: `2008`, `A`, `2008 윤리 전공 A`. B 시험지는 따로 만듭니다.
2. **PDF 업로드와 추출**에서 파일을 선택하고 **PDF 업로드**를 누릅니다. 최대 25MB·500쪽입니다. 파일명·SHA256·페이지 수가 표시됩니다. 같은 내용의 PDF는 기존 문서를 재사용합니다.
3. **텍스트 추출 · 문항 분리**를 누릅니다. 페이지별 텍스트를 추출하고 번호·레이아웃·문항 순서를 이용해 후보를 만듭니다.
4. **문항 검토와 저장**에서 번호·내용·출처 페이지를 수정합니다. 출처 페이지는 `1, 2`처럼 입력합니다. 원본 후보가 포함한 페이지 범위 안에서만 수정할 수 있습니다.
5. 필요하면 **다음 문항과 합치기**를 누릅니다. 분리할 때는 내용 입력창의 원하는 위치에 커서를 놓고 **커서 위치에서 분리**를 누릅니다. 새 문항 번호는 임시로 가장 큰 번호+1이므로 확인합니다.
6. **수정 초안 저장**은 후보만 저장합니다. 재접속 후 같은 시험과 **이전 추출 결과**를 선택하면 이어서 작업할 수 있습니다.
7. **검토 완료 · 문항 저장**을 누르면 후보가 Question과 QuestionSource로 저장됩니다. 아래 **저장된 문항**에서 결과를 펼쳐 볼 수 있습니다.

같은 시험에 같은 번호가 이미 있으면 저장을 차단합니다. 후보 번호를 고치거나 올바른 시험을
선택하세요. 기존 문항이나 분석 결과를 자동 덮어쓰지 않습니다. 문항으로 저장한 추출 결과는
읽기 전용입니다. 후속 수정은 Phase 1 문항 API를 사용할 수 있으며, 분석 이력이 생긴 원문은 변경할 수 없습니다.

### 상태 안내

- **추출 완료 · 검토 필요**: 텍스트 추출 완료. 자동 문항 경계는 직접 확인해야 합니다.
- **일부 페이지 OCR 필요**: 텍스트 없는 페이지와 텍스트 있는 페이지가 섞여 있습니다. 저장해도 빠진 스캔 내용이 복구되지는 않습니다.
- **OCR 필요**: 텍스트 층이 없습니다. 이번 버전은 OCR을 제공하지 않습니다.
- **문항 저장 완료**: 검토한 후보가 문항 DB에 반영되었습니다. AI 정답 분석의 confirmed/corrected와 별개의 상태입니다.

빈 페이지도 텍스트가 없는 페이지로 표시될 수 있습니다. 페이지별 추출 원문을 확인하세요.

## 저장 방식과 보호 규칙

- 원본 PDF는 `storage/pdfs/<SHA256>.pdf`에 저장합니다. 업로드 파일명을 경로로 사용하지 않습니다.
- `documents`: 파일명, SHA256, 페이지 수. 같은 PDF를 여러 시험에 연결할 수 있습니다.
- `extraction_runs`: 시험별 추출 실행, 버전, 원본 후보, 수정 후보, 경고, 수정 리비전.
- `document_pages`: 실행별 페이지 번호·텍스트·추출 상태.
- `questions`: 검토한 문항 내용과 별도로 보존한 자동 추출 원문.
- `question_sources`: 문항별 PDF와 출처 페이지. 여러 페이지를 연결할 수 있습니다.
- 원본 후보와 페이지 텍스트는 수정 API로 덮어쓰지 않습니다. 문항을 분리하면 원본 참조를 공유할 수 있습니다.
- 수정 리비전이 다르면 저장을 차단하며, 번호 충돌 시 전체 문항 저장을 취소합니다.
- PDF, DB, 업로드 폴더, `.env`, 개인키는 `.gitignore`로 제외합니다. 샘플도 실제 기출처럼 취급하지 않습니다.

환경변수는 서버 실행 전에 설정합니다. `.env`는 자동으로 로드하지 않습니다.
`DATABASE_URL`로 DB를, `PDF_STORAGE_DIR`로 파일 저장 폴더를 변경합니다.

## 테스트

```bash
.venv/bin/pytest -q
.venv/bin/alembic check
```

Windows는 `.venv/bin/` 대신 `.venv\Scripts\`를 사용합니다.
테스트가 PDF를 메모리에서 직접 생성합니다. 실제 기출 PDF나 API key가 필요 없습니다.
Phase 1 7개, Phase 2 API·추출 7개, 실제 Chromium 브라우저 흐름 1개,
Windows 호환 회귀 테스트 7개로 총 22개입니다.
브라우저 테스트는 Chromium이 없으면 skipped로 표시됩니다. 로컬 테스트에서 브라우저를 지정하려면:

```bash
BROWSER_EXECUTABLE=/usr/bin/chromium .venv/bin/pytest -q tests/test_browser.py
```

검증 항목: A/B 분리, CRUD·참조 제약·검수 리비전, 한국어 추출, 다중 페이지 문항,
2단 편집, 중복 업로드, 스캔 감지, 원문 보존, 합치기·분리·저장 충돌,
브라우저 업로드·수정·재접속·저장. 브라우저 테스트는 별도 임시 DB와 서버를 사용합니다.

## PostgreSQL (선택)

SQLite는 단일 개발 인스턴스용입니다. 동시 사용에는 PostgreSQL을 권장합니다.

```bash
export POSTGRES_PASSWORD='직접 지정한 개발용 비밀번호'
docker compose up -d db
export DATABASE_URL='postgresql+psycopg://ethics:URL인코딩된비밀번호@localhost:5432/ethics'
.venv/bin/alembic upgrade head
.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000
```

테스트에는 별도 DB를 사용합니다. 테스트별 임의 이름의 스키마를 생성하고 해당 스키마만 삭제합니다.

```bash
TEST_DATABASE_URL='postgresql+psycopg://user:password@localhost/test_db' .venv/bin/pytest -q
```

## 주요 API

| 경로 | 기능 |
|---|---|
| `/exams`, `/documents`, `/areas`, `/thinkers`, `/concepts`, `/question-types` | Phase 1 CRUD |
| `/exams/{id}/upload` | POST multipart PDF 업로드·중복 감지·시험 연결 |
| `/exams/{id}/uploaded-documents` | GET 시험별 문서 |
| `/exams/{id}/documents/{document_id}/extract` | POST 페이지 추출·문항 후보 생성 |
| `/exams/{id}/extractions` | GET 추출 이력 |
| `/extractions/{id}` | GET 원문·후보·페이지 / PUT 후보 전체 수정 |
| `/extractions/{id}/save` | POST 검토 후보를 문항으로 저장 |
| `/questions` | POST/GET: 문항 저장·검색 |
| `/questions/{id}` | GET/PUT/DELETE: 분석 이력 생성 후 변경·삭제 금지 |
| `/questions/{id}/analyses` | POST/GET: 분석 초안 저장·이력 조회 |
| `/analyses/{id}/corrections`, `/analyses/{id}/confirm` | 수정본 생성·검수 확정 |
| `/published-analyses` | GET 문항별 현재 확정 분석 |

시험 업무 코드는 `2008_A`, 내부 연결 ID는 UUID입니다. PUT은 전체 필드 대체입니다.
추출 수정·문항 저장은 `expected_revision`이 필요합니다. 상세 스키마는 `/docs`에서 확인합니다.

## 아직 구현하지 않은 기능

OCR, 실제 LLM 호출, AI 정답 검수 전용 화면, 통계, 공부 우선순위, 인증·권한, 공개 배포.
PDF 추출은 동기 실행하므로 큰 파일은 시간이 걸릴 수 있습니다. 작업 큐·진행률은 후속 작업입니다.
표·복잡한 다단 편집·지문 안의 번호를 완벽하게 분리하지는 못합니다. 보수적인 2단 감지와
여러 번호 형식을 지원하며, 번호가 없으면 전체 텍스트를 임시 후보로 표시합니다.
선행 안내문은 문항에서 제외되지만 페이지 원문에 보존됩니다. 문항별 지문·선택지의 자동 구조화는 후속 작업입니다.
로컬 개발용 서버입니다. 공개 서비스 전 인증·사용자 감사·처리 시간 제한을 추가해야 합니다.

다음 단계: [docs/roadmap.md](docs/roadmap.md)

## Windows 호환성 유지

`requirements.lock`의 uvloop는 `sys_platform != "win32"` 조건으로 Windows에서 제외됩니다.
Windows에서는 asyncio를 사용합니다. colorama는 Windows에서만 설치합니다.
플랫폼 조건이 손실되므로 `pip freeze` 출력으로 이 파일을 그대로 덮어쓰지 마세요.

업로드는 임시 파일 쓰기 핸들을 닫은 다음 PDF를 읽습니다. PDF 읽기 핸들도 닫은 후
파일을 이동하며, 바깥 finally에서 임시 파일을 정리합니다. 유효하지 않은 PDF, 크기 초과,
쓰기·이동 실패에도 임시 파일이 남지 않는지 회귀 테스트로 검사합니다.
파일 잠금 오류를 무시하거나 PermissionError를 숨기는 방식을 사용하지 않습니다.

Windows/Linux CI는 Python 3.12/3.13에서 전체 lockfile 설치, pip check,
마이그레이션과 모든 테스트를 실행합니다. CI는 Playwright Chromium을 설치해
브라우저 테스트가 skipped되지 않도록 합니다.

Windows에서 이번 수정 적용하기(기존 설치 폴더의 PowerShell):

```powershell
git pull origin main
.venv\Scripts\python.exe -m pip install -r requirements.lock
.venv\Scripts\alembic.exe upgrade head
.venv\Scripts\uvicorn.exe app.main:app --host 127.0.0.1 --port 8000
```

실행 중이던 서버는 먼저 Ctrl+C로 종료한 뒤 다시 실행하세요.
