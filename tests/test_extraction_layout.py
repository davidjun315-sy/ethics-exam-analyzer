from io import BytesIO

import pytest
from reportlab.pdfgen import canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont

from app.extraction import number, split_questions
from test_pdf import setup_upload, extract


@pytest.mark.parametrize('text, expected', [
    ('1.본문', 1), ('  2 .  본문', 2), ('3．본문', 3), ('4번본문', 4),
    ('5', 5), ('6)', 6), ('문항 7 본문', 7), ('8.\u200b본문', 8),
    ('９．본문', 9), ('1.5 계산', None), ('① 선택지', None),
])
def test_number_formats(text, expected):
    assert number(text) == expected


def layout_pdf(numbers=None, circled=False):
    pdfmetrics.registerFont(UnicodeCIDFont('HYSMyeongJo-Medium'))
    out = BytesIO()
    c = canvas.Canvas(out, pagesize=(600, 800))
    c.setFont('HYSMyeongJo-Medium', 12)
    if numbers:
        for i, n in enumerate(numbers):
            c.drawString(40, 710-i*70, f'{n}. 윤리 사상가에 관한 다음 물음에 답하시오.')
    elif circled:
        c.drawString(40, 710, '① 첫 문항의 본문을 설명하시오.')
        c.drawString(40, 510, '② 둘째 문항의 본문을 설명하시오.')
    else:
        # Spanning header previously prevented the midpoint-based column detector.
        c.drawString(95, 775, '교원 임용시험 윤리 전공 문항 검수용 가상 시험지 안내문입니다.')
        c.drawString(40, 710, '1.첫 문항의 본문을 설명하시오.')
        c.drawString(40, 570, '2')
        c.drawString(75, 550, '둘째 문항: 번호가 독립된 줄입니다.')
        c.drawString(40, 430, '3．셋째 문항을 설명하시오.')
        c.drawString(330, 710, '4번넷째 문항을 설명하시오.')
        c.drawString(350, 680, '① 지문 내부 선택지입니다.')
        c.drawString(330, 570, '5')
        c.drawString(344, 570, '.')
        c.drawString(360, 570, '다섯째 문항을 설명하시오.')
        c.drawString(330, 430, '6. 여섯째 문항을 설명하시오.')
        c.drawString(360, 400, '7. 지문 내부 목록: 문항이 아닙니다.')
        c.drawString(295, 12, '1')
    c.save()
    return out.getvalue()


def test_coordinates_columns_standalone_and_header(client):
    exam, doc, _ = setup_upload(client, layout_pdf())
    run = extract(client, exam, doc)
    assert [c['question_number'] for c in run['candidates']] == [1, 2, 3, 4, 5, 6]
    diag = run['pages'][0]['diagnostics']
    assert diag['two_columns']
    assert diag['layout_number_order'] == [1, 2, 3, 4, 5, 6]
    assert diag['reading_order_changed']
    assert any(l['number'] == 7 and not l['accepted'] and '들여쓰기' in l['reason'] for l in diag['lines'])
    assert '둘째 문항' in run['candidates'][1]['text']
    assert not run['missing_numbers']
    assert run['extractor_version'].endswith('v2')
    assert client.get(f"/extractions/{run['id']}").json()['pages'][0]['diagnostics'] == diag


def test_gap_warnings_manual_correction_and_save(client):
    exam, doc, _ = setup_upload(client, layout_pdf(numbers=[1, 3, 4, 6, 8, 10, 12]))
    run = extract(client, exam, doc)
    assert run['missing_numbers'] == [2, 5, 7, 9, 11]
    assert any('2번 문항 경계 누락 가능성' in w for w in run['warnings'])
    url = f"/extractions/{run['id']}"
    assert client.post(url+'/save', json={'expected_revision': 1}).status_code == 422
    candidates = run['candidates']
    candidates.append({'question_number': 2, 'text': '수동 보정 문항', 'pages': [1], 'source_indexes': [0]})
    edited = client.put(url, json={'expected_revision': 1, 'candidates': sorted(candidates, key=lambda c:c['question_number'])})
    assert edited.status_code == 200, edited.text
    assert edited.json()['missing_numbers'] == [5, 7, 9, 11]
    assert not any('2번 문항 경계 누락 가능성' in w for w in edited.json()['warnings'])
    saved = client.post(url+'/save', json={'expected_revision': 2, 'acknowledge_missing': True})
    assert saved.status_code == 200
    assert len(client.get(f"/questions?exam_id={exam['id']}").json()) == 8


def test_circled_numbers_require_explicit_mode(client):
    exam, doc, _ = setup_upload(client, layout_pdf(circled=True))
    default = extract(client, exam, doc)
    assert any(l['kind'] == 'choice' and not l['accepted'] for l in default['pages'][0]['diagnostics']['lines'])
    response = client.post(f"/exams/{exam['id']}/documents/{doc['id']}/extract", json={'allow_circled': True, 'column_mode': 'single'})
    assert response.status_code == 201
    assert [c['question_number'] for c in response.json()['candidates']] == [1, 2]


def test_gaps_and_out_of_order_not_silent():
    candidates, warnings = split_questions([(1,'1. one\n3. three\n2. two')])
    assert [c['question_number'] for c in candidates] == [1, 3]
    assert any('2번 문항 경계 누락 가능성' in w for w in warnings)
    assert any('역순' in w for w in warnings)


def test_caption_does_not_shift_question_margin(client):
    out = BytesIO()
    c = canvas.Canvas(out, pagesize=(600, 800))
    c.drawString(10, 780, 'Reference heading')
    c.drawString(40, 710, '1. First question')
    c.drawString(40, 510, '2. Second question')
    c.save()
    exam, doc, _ = setup_upload(client, out.getvalue())
    run = extract(client, exam, doc)
    assert [x['question_number'] for x in run['candidates']] == [1, 2]


def test_staggered_columns_do_not_require_shared_baselines(client):
    out = BytesIO()
    c = canvas.Canvas(out, pagesize=(600, 800))
    for x, y, n in [(40, 720, 1), (40, 450, 2), (330, 650, 3), (330, 390, 4)]:
        c.drawString(x, y, f'{n}. Question {n}')
        c.drawString(x, y-25, 'Question body')
    c.save()
    exam, doc, _ = setup_upload(client, out.getvalue())
    run = extract(client, exam, doc)
    assert run['pages'][0]['diagnostics']['two_columns']
    assert [q['question_number'] for q in run['candidates']] == [1, 2, 3, 4]
