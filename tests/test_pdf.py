from io import BytesIO
from reportlab.pdfgen import canvas
from app.extraction import split_questions


def pdf_bytes(scan=False, columns=False):
    out = BytesIO()
    c = canvas.Canvas(out, pagesize=(600, 800))
    if not scan:
        c.drawString(40, 740, '1. Explain the ethical concept.')
        c.drawString(40, 715, 'First question begins on page one.')
        if columns:
            c.drawString(340, 740, '2. Compare two thinkers.')
            c.drawString(340, 715, 'Right column question.')
        else:
            c.showPage()
            c.drawString(40, 740, 'Continuation of the first question.')
            c.drawString(40, 680, '2. Compare two thinkers.')
            c.drawString(40, 655, 'Second question text.')
    else:
        # Raster content only: no text layer.
        from PIL import Image
        from reportlab.lib.utils import ImageReader
        image = Image.new('RGB', (200, 100), 'white')
        c.drawImage(ImageReader(image), 40, 650, 200, 100)
    c.save()
    return out.getvalue()


def setup_upload(client, content=None):
    exam = client.post('/exams', json={'year': 2025, 'exam_part': 'A', 'title': 'PDF test'}).json()
    content = content or pdf_bytes()
    response = client.post(f"/exams/{exam['id']}/upload", files={'file': ('sample.pdf', content, 'application/pdf')})
    assert response.status_code == 201, response.text
    return exam, response.json()['document'], content


def extract(client, exam, document):
    response = client.post(f"/exams/{exam['id']}/documents/{document['id']}/extract")
    assert response.status_code == 201, response.text
    return response.json()


def test_upload_extract_edit_save_and_reload(client):
    exam, doc, data = setup_upload(client)
    import hashlib
    assert doc['sha256'] == hashlib.sha256(data).hexdigest()
    assert doc['page_count'] == 2
    duplicate = client.post(f"/exams/{exam['id']}/upload", files={'file': ('renamed.pdf', data)})
    assert duplicate.json()['duplicate'] is True
    assert duplicate.json()['document']['id'] == doc['id']
    run = extract(client, exam, doc)
    assert run['status'] == 'extracted'
    assert len(run['pages']) == 2 and run['pages'][1]['page_number'] == 2
    assert len(run['candidates']) == 2
    assert run['candidates'][0]['pages'] == [1, 2]
    assert 'Continuation' in run['candidates'][0]['text']
    edited = run['candidates']
    edited[0]['text'] = 'Corrected question text'
    response = client.put(f"/extractions/{run['id']}", json={'expected_revision': 1, 'candidates': edited})
    assert response.status_code == 200
    assert client.get(f"/extractions/{run['id']}").json()['original_candidates'][0]['text'].startswith('1.')
    saved = client.post(f"/extractions/{run['id']}/save", json={'expected_revision': 2})
    assert saved.status_code == 200, saved.text
    rows = client.get(f"/questions?exam_id={exam['id']}").json()
    assert len(rows) == 2
    assert rows[0]['question_text'] == 'Corrected question text'
    assert rows[0]['raw_text'].startswith('1.')
    assert {s['page_number'] for s in rows[0]['sources']} == {1, 2}
    assert client.post(f"/extractions/{run['id']}/save", json={'expected_revision': 3}).status_code == 409
    assert client.get('/').status_code == 200
    assert 'PDF' in client.get('/').text
    assert client.get('/static/app.js').status_code == 200


def test_scan_pdf_needs_ocr(client):
    exam, doc, _ = setup_upload(client, pdf_bytes(scan=True))
    run = extract(client, exam, doc)
    assert run['status'] == 'needs_ocr'
    assert run['pages'][0]['extraction_status'] == 'needs_ocr'
    assert run['candidates'] == []
    assert client.post(f"/extractions/{run['id']}/save", json={'expected_revision': 1}).status_code == 422


def test_two_column_order(client):
    exam, doc, _ = setup_upload(client, pdf_bytes(columns=True))
    run = extract(client, exam, doc)
    assert [x['question_number'] for x in run['candidates']] == [1, 2]
    assert 'First question' in run['candidates'][0]['text']
    assert 'Right column' in run['candidates'][1]['text']
    assert run['warnings']


def test_merge_split_and_conflicts(client):
    exam, doc, _ = setup_upload(client)
    run = extract(client, exam, doc)
    merged = [{'question_number': 1, 'text': 'Merged content', 'pages': [1, 2], 'source_indexes': [0, 1]}]
    url = f"/extractions/{run['id']}"
    assert client.put(url, json={'expected_revision': 1, 'candidates': merged}).status_code == 200
    assert client.put(url, json={'expected_revision': 1, 'candidates': merged}).status_code == 409
    split = [{**merged[0], 'text': 'Split first'}, {**merged[0], 'question_number': 2, 'text': 'Split second', 'pages': [2]}]
    assert client.put(url, json={'expected_revision': 2, 'candidates': split}).status_code == 200
    assert client.post(url+'/save', json={'expected_revision': 3}).status_code == 200
    rerun = extract(client, exam, doc)
    assert client.post(f"/extractions/{rerun['id']}/save", json={'expected_revision': 1}).status_code == 409
    assert len(client.get(f"/questions?exam_id={exam['id']}").json()) == 2


def test_invalid_upload_and_candidate_sources(client):
    exam, doc, _ = setup_upload(client)
    for filename, content in [('fake.pdf', b'not a pdf'), ('file.txt', pdf_bytes()), ('broken.pdf', b'%PDF-broken')]:
        assert client.post(f"/exams/{exam['id']}/upload", files={'file': (filename, content)}).status_code == 422
    run = extract(client, exam, doc)
    for candidate in [{'question_number': 1, 'text': 'bad', 'pages': [999], 'source_indexes': [0]},
                      {'question_number': 1, 'text': 'bad', 'pages': [1], 'source_indexes': [-1]}]:
        assert client.put(f"/extractions/{run['id']}", json={'expected_revision': 1, 'candidates': [candidate]}).status_code == 422
    assert client.get(f"/extractions/{run['id']}").json()['revision'] == 1


def test_fallback_and_multiple_numbering_formats():
    candidates, warnings = split_questions([(1, 'Unnumbered text')])
    assert candidates[0]['text'] == 'Unnumbered text' and warnings
    rows, _ = split_questions([(1, '1) First\ncontinued\n문항 2 Second\n3번 Third')])
    assert [x['question_number'] for x in rows] == [1, 2, 3]


def test_korean_text_extraction(client):
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.cidfonts import UnicodeCIDFont
    pdfmetrics.registerFont(UnicodeCIDFont('HYSMyeongJo-Medium'))
    out = BytesIO()
    c = canvas.Canvas(out)
    c.setFont('HYSMyeongJo-Medium', 12)
    c.drawString(40, 740, '1. 퇴계의 사단칠정론을 설명하시오.')
    c.drawString(40, 680, '2. 이황과 이이를 비교하시오.')
    c.save()
    exam, doc, _ = setup_upload(client, out.getvalue())
    run = extract(client, exam, doc)
    assert len(run['candidates']) == 2
    assert '사단칠정론' in run['candidates'][0]['text']
    assert '이황과 이이' in run['candidates'][1]['text']
