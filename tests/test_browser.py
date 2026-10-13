"""Real browser → upload → edit/merge/split → database round trip."""
import os
import shutil
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import pytest
from playwright.sync_api import sync_playwright, expect
from test_pdf import pdf_bytes


def test_browser_pdf_workflow(tmp_path):
    executable = os.getenv('BROWSER_EXECUTABLE') or shutil.which('chromium') or shutil.which('google-chrome')
    if not executable:
        pytest.skip('Chromium is required for the browser test; set BROWSER_EXECUTABLE.')
    root = Path(__file__).resolve().parents[1]
    env = {**os.environ, 'DATABASE_URL': f'sqlite:///{tmp_path / "browser.db"}',
           'PDF_STORAGE_DIR': str(tmp_path / 'pdfs')}
    subprocess.run([sys.executable, '-m', 'alembic', 'upgrade', 'head'], cwd=root, env=env, check=True, capture_output=True)
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    url = f'http://127.0.0.1:{port}'
    with (tmp_path / 'server.log').open('w') as log:
        server = subprocess.Popen([sys.executable, '-m', 'uvicorn', 'app.main:app', '--port', str(port)], cwd=root, env=env, stdout=log, stderr=log)
        try:
            for _ in range(100):
                try:
                    urllib.request.urlopen(url + '/health', timeout=.3).close()
                    break
                except OSError:
                    if server.poll() is not None:
                        pytest.fail((tmp_path / 'server.log').read_text())
                    time.sleep(.1)
            else:
                pytest.fail('Browser test server did not start')
            with sync_playwright() as p:
                browser = p.chromium.launch(executable_path=executable, headless=True)
                page = browser.new_page(viewport={'width': 1280, 'height': 1000})
                errors = []
                page.on('pageerror', lambda e: errors.append(str(e)))
                page.goto(url)
                page.get_by_text('새 시험 만들기', exact=True).click()
                page.locator('#year').fill('2024')
                page.locator('#title').fill('Browser PDF test')
                page.get_by_role('button', name='시험 생성', exact=True).click()
                expect(page.locator('#message')).to_contain_text('시험을 생성했습니다')
                page.locator('#pdf').set_input_files({'name': 'generated.pdf', 'mimeType': 'application/pdf', 'buffer': pdf_bytes()})
                page.get_by_role('button', name='PDF 업로드', exact=True).click()
                expect(page.locator('#message')).to_contain_text('PDF 업로드가 완료')
                page.get_by_role('button', name='텍스트 추출 · 문항 분리').click()
                expect(page.locator('.candidate')).to_have_count(2)
                expect(page.locator('.candidate').first.locator('.page-input')).to_have_value('1, 2')
                page.get_by_role('button', name='다음 문항과 합치기').first.click()
                expect(page.locator('.candidate')).to_have_count(1)
                textarea = page.locator('.candidate textarea').first
                textarea.fill('First edited question.\nSecond edited question.')
                textarea.evaluate('(e) => {e.focus(); e.setSelectionRange(22,22)}')
                page.get_by_role('button', name='커서 위치에서 분리').click()
                expect(page.locator('.candidate')).to_have_count(2)
                page.locator('.candidate').nth(1).locator('.page-input').fill('2')
                page.get_by_role('button', name='수정 초안 저장').click()
                expect(page.locator('#message')).to_contain_text('수정 초안을 저장했습니다')
                page.reload()
                expect(page.locator('#exam option')).to_have_count(2)
                page.locator('#exam').select_option(label='2024_A · Browser PDF test')
                expect(page.locator('#history option')).to_have_count(2)
                page.locator('#history').select_option(index=1)
                expect(page.locator('.candidate')).to_have_count(2)
                expect(page.locator('.candidate textarea').first).to_have_value('First edited question.')
                page.get_by_role('button', name='검토 완료 · 문항 저장').click()
                expect(page.locator('#message')).to_contain_text('2개 문항을 저장했습니다')
                expect(page.locator('#questions details')).to_have_count(2)
                expect(page.locator('#save')).to_be_disabled()
                assert not errors, errors
                page.screenshot(path=str(tmp_path / 'browser-workflow.png'), full_page=True)
                browser.close()
        finally:
            server.terminate()
            server.wait(timeout=10)
