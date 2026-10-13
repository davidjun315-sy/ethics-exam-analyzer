import base64
import os
from pathlib import Path

import pytest
from botocore.stub import Stubber
from app.blob_storage import LocalObjectStorage, S3ObjectStorage


def test_local_atomic_storage_and_path_safety(tmp_path,monkeypatch):
    monkeypatch.setenv('ASSET_STORAGE_DIR',str(tmp_path))
    store=LocalObjectStorage()
    store.put('pages/1.png',b'bytes','image/png')
    assert store.read('pages/1.png')==b'bytes'
    assert store.exists('pages/1.png')
    assert not list(tmp_path.rglob('*.tmp'))
    with pytest.raises(ValueError): store.read('../escape')


def test_private_s3_adapter(monkeypatch):
    monkeypatch.setenv('OBJECT_STORAGE_BUCKET','test-bucket')
    monkeypatch.setenv('OBJECT_STORAGE_ACCESS_KEY_ID','testing')
    monkeypatch.setenv('OBJECT_STORAGE_SECRET_ACCESS_KEY','testing')
    monkeypatch.delenv('AWS_PROFILE', raising=False)
    monkeypatch.delenv('AWS_DEFAULT_PROFILE', raising=False)
    store=S3ObjectStorage()
    with Stubber(store.client) as stub:
        stub.add_response('put_object',{}, {'Bucket':'test-bucket','Key':'pages/1.png','Body':b'png','ContentType':'image/png'})
        store.put('pages/1.png',b'png','image/png')
        stub.add_response('head_object',{}, {'Bucket':'test-bucket','Key':'pages/1.png'})
        assert store.exists('pages/1.png')
        stub.add_client_error('head_object',service_error_code='404',http_status_code=404,expected_params={'Bucket':'test-bucket','Key':'missing'})
        assert not store.exists('missing')
        stub.add_client_error('head_object',service_error_code='AccessDenied',http_status_code=403,expected_params={'Bucket':'test-bucket','Key':'private'})
        from botocore.exceptions import ClientError
        with pytest.raises(ClientError):store.exists('private')


def test_production_gate_requires_password(client,monkeypatch):
    monkeypatch.setenv('APP_ENV','production')
    monkeypatch.delenv('ACCESS_PASSWORD',raising=False)
    assert client.get('/').status_code==503
    assert client.get('/health').status_code==200
    monkeypatch.setenv('ACCESS_PASSWORD','test-only-password')
    assert client.get('/').status_code==401
    assert client.get('/',auth=('owner','test-only-password')).status_code==200
    assert client.get('/documents/missing/page-assets',auth=('owner','wrong')).status_code==401


def test_postgres_url_normalization():
    from app.db import make_engine
    engine=make_engine('postgres://user:testing@localhost/database')
    assert engine.url.drivername=='postgresql+psycopg'
    engine.dispose()


def test_redis_dispatch_failure_recorded(client,monkeypatch):
    from test_pdf import setup_upload
    from redis import Redis
    monkeypatch.setenv('JOB_BACKEND','redis')
    monkeypatch.setenv('REDIS_URL','redis://localhost:1/0')
    def failed(*args,**kwargs):raise OSError('queue offline')
    monkeypatch.setattr(Redis,'from_url',failed)
    exam,doc,_=setup_upload(client)
    with pytest.raises(OSError):client.post(f"/exams/{exam['id']}/documents/{doc['id']}/render")
    from app import models as m
    from app.db import get_db
    from app.main import app
    from sqlalchemy import select
    generator=app.dependency_overrides[get_db]()
    db=next(generator)
    job=db.scalar(select(m.ProcessingJob))
    assert job.status=='failed'
    generator.close()
