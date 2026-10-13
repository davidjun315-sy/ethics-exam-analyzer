import os
from uuid import uuid4

import pytest
from sqlalchemy.orm import sessionmaker
from sqlalchemy import select
from redis import Redis
from rq import Queue, SimpleWorker
from app import models as m
from app import db as db_module
from app.main import app
from test_pdf import setup_upload


@pytest.mark.skipif(not os.getenv('TEST_REDIS_URL'),reason='Optional Redis integration requires TEST_REDIS_URL')
def test_real_redis_queue_to_worker_to_candidate(client,monkeypatch):
    monkeypatch.setenv('JOB_BACKEND','redis')
    monkeypatch.setenv('REDIS_URL',os.environ['TEST_REDIS_URL'])
    connection=Redis.from_url(os.environ['TEST_REDIS_URL'])
    assert connection.ping()
    # A unique queue isolates this test; no existing Redis data is removed.
    queue_name='test_pdf_'+uuid4().hex
    import rq
    real_queue=rq.Queue
    monkeypatch.setattr(rq,'Queue',lambda name,connection:real_queue(queue_name,connection=connection))
    generator=app.dependency_overrides[db_module.get_db]()
    db=next(generator)
    monkeypatch.setattr(db_module,'SessionLocal',sessionmaker(db.get_bind(),expire_on_commit=False))
    exam,doc,_=setup_upload(client)
    response=client.post(f"/exams/{exam['id']}/documents/{doc['id']}/extract-images")
    assert response.status_code==201
    job=response.json()
    assert job['status']=='queued'
    worker=SimpleWorker([real_queue(queue_name,connection=connection)],connection=connection)
    worker.work(burst=True,with_scheduler=False)
    status=client.get('/processing-jobs/'+job['id']).json()
    assert status['status']=='completed',status
    run=client.get('/multimodal-extractions/'+status['result']['extraction_run_id']).json()
    assert len(run['structured_candidates'])==2
    generator.close()
