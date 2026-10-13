"""Idempotent synthetic fixtures, never real exam questions."""
from fastapi.testclient import TestClient
from .main import app


def seed():
    with TestClient(app) as client:
        def post(path, data):
            response = client.post(path, json=data)
            response.raise_for_status()
            return response.json()

        if any(x["exam_id"] == "2008_SAMPLE_A" for x in client.get("/exams?limit=200").json()):
            print("샘플 데이터가 이미 있습니다. 변경하지 않았습니다.")
            return
        areas = client.get("/areas?limit=200").json()
        area = next((x for x in areas if x["name"] == "한국윤리"), None) or post("/areas", {"name": "한국윤리"})
        thinkers = client.get("/thinkers?limit=200").json()
        if not any(x["canonical_name"] == "이황" for x in thinkers):
            post("/thinkers", {"canonical_name": "이황", "aliases": ["퇴계", "퇴계 이황", "李滉"], "area_id": area["id"]})
        concepts = client.get("/concepts?limit=200").json()
        if not any(x["canonical_name"] == "사단칠정론" for x in concepts):
            post("/concepts", {"canonical_name": "사단칠정론", "aliases": ["사단칠정"], "area_id": area["id"]})
        types = client.get("/question-types?limit=200").json()
        if not any(x["name"] == "개념 설명" for x in types):
            post("/question-types", {"name": "개념 설명"})
        for part in ["SAMPLE_A", "SAMPLE_B"]:
            exam = post("/exams", {"year": 2008, "exam_part": part, "title": "가상 샘플 — 실제 기출 아님"})
            doc = post("/documents", {"filename": f"synthetic_{part}.pdf", "storage_key": f"synthetic/{part}.pdf", "sha256": "0" * 64, "page_count": 1})
            client.put(f"/exams/{exam['id']}/documents/{doc['id']}").raise_for_status()
            question = post("/questions", {"exam_id": exam["id"], "question_number": 1,
                "question_text": "[가상 문항] 퇴계의 사단칠정론을 설명하시오.",
                "raw_text": "[가상 문항] 퇴계의 사단칠정론을 설명하시오.",
                "sources": [{"document_id": doc["id"], "page_number": 1}]})
            post(f"/questions/{question['id']}/analyses", {"area_id": area["id"], "primary_thinkers": ["퇴계"],
                "primary_concept": "사단칠정", "question_types": ["개념 설명"], "answer": None,
                "explanation": "가상 분석입니다. 실제 정답·해설이 아닙니다.",
                "evidence": [{"kind": "question", "text": "퇴계"}, {"kind": "theory", "text": "검수 흐름 검증용 가상 근거"}],
                "model": "synthetic-fixture", "analysis_version": "sample-v1"})
        print("가상 A/B 시험, 문항, 미검수 분석을 생성했습니다. 실제 PDF 파일은 생성하지 않습니다.")


if __name__ == "__main__":
    seed()
