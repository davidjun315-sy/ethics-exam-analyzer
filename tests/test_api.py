def post(client, path, data, status=201):
    response = client.post(path, json=data)
    assert response.status_code == status, response.text
    return response.json()


def setup_question(client, part="A"):
    exam = post(client, "/exams", {"year": 2008, "exam_part": part, "title": "테스트"})
    doc = post(client, "/documents", {"filename": f"{part}.pdf", "storage_key": part, "sha256": "a" * 64, "page_count": 2})
    assert client.put(f"/exams/{exam['id']}/documents/{doc['id']}").status_code == 200
    payload = {"exam_id": exam["id"], "question_number": 1, "question_text": "퇴계의 사단칠정론을 설명하시오.",
               "raw_text": "퇴계의 사단칠정론을 설명하시오.", "sources": [{"document_id": doc["id"], "page_number": 1}]}
    question = post(client, "/questions", payload)
    return exam, doc, question, payload


def analysis_payload(client):
    post(client, "/thinkers", {"canonical_name": "이황", "aliases": ["퇴계", "퇴계 이황"]})
    post(client, "/concepts", {"canonical_name": "사단칠정론", "aliases": ["사단칠정"]})
    post(client, "/question-types", {"name": "개념 설명"})
    return {"primary_thinkers": ["퇴계 이황"], "primary_concept": "사단칠정", "question_types": ["개념 설명"],
            "answer": "샘플", "explanation": "샘플 해설", "ai_confidence": 0.5,
            "evidence": [{"kind": "question", "text": "퇴계"}, {"kind": "theory", "text": "샘플 이론"}],
            "model": "test", "analysis_version": "v1"}


def test_ab_exams_and_question_crud(client):
    a, _, qa, payload = setup_question(client, "A")
    b, _, qb, _ = setup_question(client, "B")
    assert a["exam_id"] == "2008_A" and b["exam_id"] == "2008_B"
    assert qa["id"] != qb["id"]
    assert len(client.get("/questions?year=2008").json()) == 2
    post(client, "/questions", payload, 409)
    payload["question_text"] = "수정한 원문"
    assert client.put(f"/questions/{qa['id']}", json=payload).status_code == 200
    assert client.delete(f"/questions/{qa['id']}").status_code == 200
    assert client.get(f"/questions/{qa['id']}").status_code == 404


def test_document_link_and_page_validation(client):
    _, _, _, payload = setup_question(client)
    payload["question_number"] = 2
    payload["sources"][0]["page_number"] = 3
    post(client, "/questions", payload, 422)
    payload["sources"][0] = {"document_id": "missing", "page_number": 1}
    post(client, "/questions", payload, 404)


def test_review_revisions_and_publication(client):
    _, _, q, question_payload = setup_question(client)
    payload = analysis_payload(client)
    a = post(client, f"/questions/{q['id']}/analyses", payload)
    assert a["primary_thinkers"] == ["이황"]
    assert a["primary_concept"] == "사단칠정론"
    assert client.get("/published-analyses").json() == []
    confirmed = post(client, f"/analyses/{a['id']}/confirm", {}, 200)
    assert confirmed["review_status"] == "confirmed"
    correction = post(client, f"/analyses/{a['id']}/corrections", {**payload, "expected_revision": 1, "answer": "수정 답안"})
    assert correction["review_status"] == "unreviewed"
    assert correction["revision_number"] == 2
    assert client.get("/published-analyses").json()[0]["id"] == a["id"]
    post(client, f"/analyses/{correction['id']}/confirm", {}, 409)
    corrected = post(client, f"/analyses/{correction['id']}/confirm", {"expected_publication_id": a["id"]}, 200)
    assert corrected["review_status"] == "corrected"
    published = client.get("/published-analyses").json()
    assert len(published) == 1 and published[0]["answer"] == "수정 답안"
    assert client.get(f"/analyses/{a['id']}").json()["answer"] == "샘플"
    assert client.put(f"/questions/{q['id']}", json=question_payload).status_code == 409
    assert client.delete(f"/questions/{q['id']}").status_code == 409
    post(client, f"/analyses/{a['id']}/corrections", {**payload, "expected_revision": 1}, 409)
    assert len(client.get(f"/review-events?analysis_id={correction['id']}").json()) == 2


def test_invalid_ai_results_rollback(client):
    _, _, q, _ = setup_question(client)
    payload = analysis_payload(client)
    for bad in [{"primary_thinkers": ["미등록"]}, {"ai_confidence": 2},
                {"evidence": [{"kind": "question", "text": "없는 인용"}]},
                {"related_thinkers": ["이황"]}, {"review_status": "confirmed"}]:
        post(client, f"/questions/{q['id']}/analyses", {**payload, **bad}, 422)
    assert client.get(f"/questions/{q['id']}/analyses").json() == []
    a = post(client, f"/questions/{q['id']}/analyses", {**payload, "evidence": [{"kind": "theory", "text": "이론"}]})
    post(client, f"/analyses/{a['id']}/confirm", {}, 422)


def test_master_aliases_and_cycles(client):
    thinker = post(client, "/thinkers", {"canonical_name": "이황", "aliases": ["퇴계"]})
    post(client, "/thinkers", {"canonical_name": "다른 이름", "aliases": ["퇴 계"]}, 409)
    assert client.put(f"/thinkers/{thinker['id']}", json={"canonical_name": "이황", "aliases": ["퇴계 이황"]}).status_code == 200
    post(client, "/thinkers", {"canonical_name": "새 인물", "aliases": ["퇴계"]})
    parent = post(client, "/concepts", {"canonical_name": "부모"})
    child = post(client, "/concepts", {"canonical_name": "자식", "parent_concept_id": parent["id"]})
    assert client.put(f"/concepts/{parent['id']}", json={"canonical_name": "부모", "parent_concept_id": child["id"]}).status_code == 422
    assert client.delete(f"/concepts/{parent['id']}").status_code == 409


def test_reference_protection_and_multi_document(client):
    exam, document, q, payload = setup_question(client)
    assert client.delete(f"/documents/{document['id']}").status_code == 409
    assert client.delete(f"/exams/{exam['id']}").status_code == 409
    exam_b = post(client, "/exams", {"year": 2008, "exam_part": "B", "title": "B"})
    assert client.put(f"/exams/{exam_b['id']}/documents/{document['id']}").status_code == 200
    payload["exam_id"] = exam_b["id"]
    payload["sources"].append({"document_id": document["id"], "page_number": 2})
    created = post(client, "/questions", payload)
    assert len(created["sources"]) == 2


def test_health_and_openapi(client):
    assert client.get("/health").json()["status"] == "ok"
    spec = client.get("/openapi.json").json()
    assert "/analyses/{id}/confirm" in spec["paths"]
