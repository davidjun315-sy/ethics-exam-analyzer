import os
from uuid import uuid4
import pytest
from sqlalchemy import text
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker
from app.db import Base, make_engine, get_db
from app.main import app


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("PDF_STORAGE_DIR", str(tmp_path / "pdfs"))
    url = os.getenv("TEST_DATABASE_URL")
    schema = "test_" + uuid4().hex
    admin = None
    if url:
        admin = make_engine(url)
        with admin.begin() as connection:
            connection.execute(text(f'CREATE SCHEMA "{schema}"'))
        engine = make_engine(url)
        from sqlalchemy import event
        @event.listens_for(engine, "connect")
        def search_path(connection, _):
            with connection.cursor() as cursor:
                cursor.execute(f'SET search_path TO "{schema}"')
            connection.commit()
    else:
        engine = make_engine(f"sqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(engine)
    sessions = sessionmaker(engine, expire_on_commit=False)
    def override():
        with sessions() as db:
            yield db
    app.dependency_overrides[get_db] = override
    with TestClient(app) as client:
        yield client
    app.dependency_overrides.clear()
    engine.dispose()
    if admin:
        with admin.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin.dispose()
