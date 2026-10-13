import hashlib
from io import BytesIO

import pytest
from PIL import Image
from pydantic import ValidationError
from sqlalchemy import select
from app import models as m
from app.db import get_db
from app.main import app
from app.multimodal_provider import ExtractionOutput, Source
from test_pdf import setup_upload, pdf_bytes


def image_extract(client, exam, doc):
    response=client.post(f"/exams/{exam['id']}/documents/{doc['id']}/extract-images")
    assert response.status_code==201, response.text
    job=response.json()
    assert job['status']=='completed'
    return client.get('/multimodal-extractions/'+job['result']['extraction_run_id']).json()


@pytest.mark.parametrize('scan',[False,True])
def test_image_pipeline_and_review(client,scan):
    exam,doc,data=setup_upload(client,pdf_bytes(scan=scan))
    render_url=f"/exams/{exam['id']}/documents/{doc['id']}/render"
    rendered=client.post(render_url)
    assert rendered.status_code==201,rendered.text
    page_assets=rendered.json()['result']['page_assets']
    assert len(page_assets)==doc['page_count']
    for asset in page_assets:
        image=client.get(asset['image_url'])
        assert image.status_code==200
        assert hashlib.sha256(image.content).hexdigest()==asset['sha256']
        with Image.open(BytesIO(image.content)) as png:
            assert png.size==(asset['width_px'],asset['height_px'])
    duplicate=client.post(f"/exams/{exam['id']}/upload",files={'file':('again.pdf',data)})
    assert duplicate.json()['duplicate']
    assert [a['id'] for a in client.post(render_url).json()['result']['page_assets']]==[a['id'] for a in page_assets]
    run=image_extract(client,exam,doc)
    assert run['engine']=='multimodal'
    assert run['provider_label']=='테스트 추출(Mock Provider)'
    candidates=run['structured_candidates']
    assert len(candidates)==doc['page_count']
    if scan: assert '스캔' in candidates[0]['question_text']
    questions=[]
    for c in candidates:
        payload={key:value for key,value in c.items() if key not in {'id','revision','review_status'}}
        questions.append(payload)
    questions[0].update(question_text='사용자 검토 원문', passage='검토 지문',choices=[{'label':'①','text':'첫 선택지'}],
                        visual_elements=[{'type':'table','page_number':1,'bbox':[.1,.2,.5,.6]}], uncertain_fields=[])
    questions[0]['sources'][0]['bbox']=[.1,.1,.8,.8]
    edited=client.put(f"/multimodal-extractions/{run['id']}",json={'expected_revision':run['revision'],'output':{'questions':questions}})
    assert edited.status_code==200,edited.text
    saved=client.post(f"/multimodal-extractions/{run['id']}/save",json={'expected_revision':edited.json()['revision']})
    assert saved.status_code==200,saved.text
    rows=client.get(f"/questions?exam_id={exam['id']}").json()
    assert rows[0]['question_text']=='사용자 검토 원문' and rows[0]['passage']=='검토 지문'
    assert rows[0]['choices']==[{'label':'①','text':'첫 선택지'}]
    assert rows[0]['sources'][0]['page_region_id']
    assert len(rows[0]['sources'][0]['regions'])==2
    # Raw original output survives user editing; saved candidate revisions remain auditable.
    assert '사용자 검토 원문' not in rows[0]['raw_text']
    db=next(app.dependency_overrides[get_db]())
    assert db.scalar(select(m.ExtractionBatch.id))
    assert db.scalar(select(m.CandidateSource.candidate_id))
    assert len(db.scalars(select(m.ExtractionCandidate)).all())==len(candidates)*2
    db.close()
    assert client.get('/multimodal/schema').json()['$defs']['MultimodalQuestion']
    assert client.post(f"/extractions/{run['id']}/save",json={'expected_revision':3}).status_code==409


@pytest.mark.parametrize('bbox', [[-.1,0,1,1],[0,0,1.1,1],[.5,0,.2,1],[0,1,1,1],[0,0,float('nan'),1],[0,0,1]])
def test_bbox_validation(bbox):
    with pytest.raises(ValidationError): Source(page_number=1,bbox=bbox)


def test_invalid_references_and_stale_edit(client):
    exam,doc,_=setup_upload(client)
    run=image_extract(client,exam,doc)
    candidate=run['structured_candidates'][0]
    q={k:v for k,v in candidate.items() if k not in {'id','revision','review_status'}}
    q['sources'][0]['page_number']=999
    response=client.put(f"/multimodal-extractions/{run['id']}",json={'expected_revision':1,'output':{'questions':[q]}})
    assert response.status_code==422
    assert client.get(f"/multimodal-extractions/{run['id']}").json()['revision']==1
    q['sources'][0]['page_number']=1
    q['continues_to_next_page']=True
    edited=client.put(f"/multimodal-extractions/{run['id']}",json={'expected_revision':1,'output':{'questions':[q]}})
    assert edited.status_code==200
    assert client.put(f"/multimodal-extractions/{run['id']}",json={'expected_revision':1,'output':{'questions':[q]}}).status_code==409
    assert client.post(f"/multimodal-extractions/{run['id']}/save",json={'expected_revision':2}).status_code==422


def test_mock_ignores_regex_boundary_engine(client,monkeypatch):
    from app import extraction
    monkeypatch.setattr(extraction,'split_questions',lambda *a,**k: pytest.fail('Legacy boundaries used'))
    exam,doc,_=setup_upload(client)
    run=image_extract(client,exam,doc)
    assert len(run['structured_candidates'])==2
