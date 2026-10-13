"""Regressions run on both OSes; emulate Windows' open-file restrictions on Linux."""
from contextlib import contextmanager
from pathlib import Path

import pytest
from packaging.markers import default_environment
from packaging.requirements import Requirement

from app import pdf_api
from test_pdf import pdf_bytes


@pytest.fixture
def windows_file_handles(monkeypatch):
    writers, readers = [], []
    create = pdf_api.NamedTemporaryFile
    open_pdf = pdf_api.pdfplumber.open
    replace, unlink = Path.replace, Path.unlink

    def tracked_create(*args, **kwargs):
        writer = create(*args, **kwargs)
        writers.append(writer)
        return writer

    @contextmanager
    def tracked_pdf(*args, **kwargs):
        # The writer must already be closed when pdfplumber opens the file.
        assert all(writer.closed for writer in writers)
        with open_pdf(*args, **kwargs) as pdf:
            readers.append(pdf.stream)
            yield pdf

    def assert_closed(path):
        if path.suffix == '.tmp':
            assert all(writer.closed for writer in writers), 'Temporary writer is still open'
            assert all(reader.closed for reader in readers), 'PDF reader is still open'

    def guarded_replace(path, target):
        assert_closed(path)
        return replace(path, target)

    def guarded_unlink(path, *args, **kwargs):
        assert_closed(path)
        return unlink(path, *args, **kwargs)

    monkeypatch.setattr(pdf_api, 'NamedTemporaryFile', tracked_create)
    monkeypatch.setattr(pdf_api.pdfplumber, 'open', tracked_pdf)
    monkeypatch.setattr(Path, 'replace', guarded_replace)
    monkeypatch.setattr(Path, 'unlink', guarded_unlink)
    return writers, readers


def new_exam(client):
    response = client.post('/exams', json={'year': 2026, 'exam_part': 'A', 'title': 'Windows regression'})
    assert response.status_code == 201
    return response.json()['id']


def test_closed_handles_upload_duplicate_extract_and_save(client, windows_file_handles):
    exam_id = new_exam(client)
    data = pdf_bytes()
    first = client.post(f'/exams/{exam_id}/upload', files={'file': ('sample.pdf', data)})
    assert first.status_code == 201, first.text
    doc = first.json()['document']
    folder = pdf_api.storage()
    assert not list(folder.glob('*.tmp'))
    assert (folder / f"{doc['sha256']}.pdf").read_bytes() == data
    # Existing destination takes the unlink branch instead of replace.
    duplicate = client.post(f'/exams/{exam_id}/upload', files={'file': ('again.pdf', data)})
    assert duplicate.status_code == 201 and duplicate.json()['duplicate']
    assert not list(folder.glob('*.tmp'))
    run = client.post(f'/exams/{exam_id}/documents/{doc["id"]}/extract')
    assert run.status_code == 201, run.text
    run = run.json()
    assert len(run['pages']) == 2 and len(run['candidates']) == 2
    saved = client.post(f'/extractions/{run["id"]}/save', json={'expected_revision': run['revision']})
    assert saved.status_code == 200, saved.text
    questions = client.get(f'/questions?exam_id={exam_id}').json()
    assert len(questions) == 2
    assert {s['page_number'] for s in questions[0]['sources']} == {1, 2}
    assert all(writer.closed for writer in windows_file_handles[0])
    assert all(reader.closed for reader in windows_file_handles[1])


@pytest.mark.parametrize('failure', ['signature', 'corrupt', 'oversize', 'write', 'replace'])
def test_failed_upload_closes_handles_and_removes_temp(client, monkeypatch, windows_file_handles, failure):
    exam_id = new_exam(client)
    data = pdf_bytes()
    expected_status = 422
    if failure == 'signature':
        data = b'not a PDF'
    elif failure == 'corrupt':
        data = b'%PDF-broken'
    elif failure == 'oversize':
        monkeypatch.setattr(pdf_api, 'MAX_BYTES', 8)
        expected_status = 413
    elif failure == 'write':
        create = pdf_api.NamedTemporaryFile
        def failing_create(*args, **kwargs):
            writer = create(*args, **kwargs)
            def failing_write(data):
                raise OSError('Simulated disk write failure')
            monkeypatch.setattr(writer, 'write', failing_write)
            return writer
        monkeypatch.setattr(pdf_api, 'NamedTemporaryFile', failing_create)
    elif failure == 'replace':
        def failing_replace(path, target):
            assert all(writer.closed for writer in windows_file_handles[0])
            raise OSError('Simulated file promotion failure')
        monkeypatch.setattr(Path, 'replace', failing_replace)
    if failure in {'write', 'replace'}:
        with pytest.raises(OSError, match='Simulated'):
            client.post(f'/exams/{exam_id}/upload', files={'file': ('failed.pdf', data)})
    else:
        response = client.post(f'/exams/{exam_id}/upload', files={'file': ('failed.pdf', data)})
        assert response.status_code == expected_status, response.text
    assert not list(pdf_api.storage().iterdir())
    assert all(writer.closed for writer in windows_file_handles[0])
    assert client.get(f'/exams/{exam_id}/uploaded-documents').json() == []


def test_platform_markers_exclude_uvloop_on_windows():
    lines = (Path(__file__).resolve().parents[1] / 'requirements.lock').read_text().splitlines()
    requirements = [Requirement(line) for line in lines if line.strip() and not line.startswith('#')]
    windows = {**default_environment(), 'sys_platform': 'win32', 'os_name': 'nt',
               'platform_system': 'Windows', 'platform_python_implementation': 'CPython'}
    linux = {**default_environment(), 'sys_platform': 'linux', 'os_name': 'posix',
             'platform_system': 'Linux', 'platform_python_implementation': 'CPython'}
    selected = lambda env: {r.name.lower() for r in requirements if r.marker is None or r.marker.evaluate(env)}
    assert 'uvloop' not in selected(windows)
    assert 'uvloop' in selected(linux)
    assert 'colorama' in selected(windows)
    assert 'fastapi' in selected(windows) and 'pdfplumber' in selected(windows)
