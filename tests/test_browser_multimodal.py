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


@pytest.mark.parametrize('scan',[False,True])
def test_browser_image_review(tmp_path,scan):
    executable=os.getenv('BROWSER_EXECUTABLE') or shutil.which('chromium') or shutil.which('google-chrome')
    if not executable and os.getenv('USE_PLAYWRIGHT_BROWSER')!='1': pytest.skip('Install Chromium for browser verification')
    root=Path(__file__).resolve().parents[1]
    env={**os.environ,'DATABASE_URL':f'sqlite:///{tmp_path / "vision.db"}','PDF_STORAGE_DIR':str(tmp_path/'pdfs')}
    subprocess.run([sys.executable,'-m','alembic','upgrade','head'],cwd=root,env=env,check=True,capture_output=True)
    with socket.socket() as sock:
        sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
    url=f'http://127.0.0.1:{port}'
    with (tmp_path/'server.log').open('w') as log:
        server=subprocess.Popen([sys.executable,'-m','uvicorn','app.main:app','--port',str(port)],cwd=root,env=env,stdout=log,stderr=log)
        try:
            for _ in range(100):
                try: urllib.request.urlopen(url+'/health',timeout=.3).close();break
                except OSError:
                    if server.poll() is not None: pytest.fail((tmp_path/'server.log').read_text())
                    time.sleep(.1)
            with sync_playwright() as p:
                browser=p.chromium.launch(**({'executable_path':executable} if executable else {}),headless=True)
                page=browser.new_page(viewport={'width':1500,'height':1000})
                errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
                page.goto(url)
                page.get_by_text('새 시험 만들기',exact=True).click()
                page.locator('#title').fill('Image browser test')
                page.get_by_role('button',name='시험 생성',exact=True).click()
                expect(page.locator('#message')).to_contain_text('시험을 생성했습니다')
                page.locator('#pdf').set_input_files({'name':'image.pdf','mimeType':'application/pdf','buffer':pdf_bytes(scan=scan)})
                page.get_by_role('button',name='PDF 업로드',exact=True).click()
                expect(page.locator('#message')).to_contain_text('PDF 업로드가 완료')
                page.get_by_role('button',name='페이지 이미지 생성',exact=True).click()
                expect(page.locator('#message')).to_contain_text('원본 페이지 이미지가 준비')
                expect(page.locator('#page-image')).to_be_visible()
                assert page.locator('#page-image').evaluate('(img)=>img.complete && img.naturalWidth>0')
                page.get_by_role('button',name='이미지 기반 테스트 추출').click()
                expect(page.locator('.vision-candidate')).to_have_count(1 if scan else 2)
                expect(page.locator('#run-info')).to_contain_text('테스트 추출(Mock Provider)')
                expect(page.locator('.region-box')).to_have_count(1)
                if not scan:
                    page.get_by_role('button',name='원본 영역 보기').nth(1).click()
                    expect(page.locator('#image-info')).to_contain_text('2쪽')
                    page.get_by_role('button',name='다음 문항과 합치기').first.click()
                    expect(page.locator('.vision-candidate')).to_have_count(1)
                area=page.locator('.vision-text').first
                area.fill('First reviewed question.\nSecond reviewed question.')
                area.evaluate('(e)=>{e.focus();e.setSelectionRange(24,24)}')
                page.get_by_role('button',name='커서 위치에서 분리').first.click()
                expect(page.locator('.vision-candidate')).to_have_count(2)
                page.locator('.vision-passage').first.fill('Reviewed passage')
                page.get_by_role('button',name='선택지 추가',exact=True).first.click()
                page.locator('.choice-label').first.fill('①')
                page.locator('.choice-text').first.fill('Choice text')
                page.locator('.source-row').first.locator('.region-page').select_option('1')
                for i,value in enumerate(['10','20','80','70']):
                    page.locator('.source-row').first.locator('.coordinate').nth(i).fill(value)
                page.get_by_role('button',name='영역 표시 갱신').first.click()
                expect(page.locator('.region-box')).to_have_count(1)
                page.locator('#image-panel').scroll_into_view_if_needed()
                image_rect=page.locator('#page-image').bounding_box()
                viewer_rect=page.locator('#image-scroll').bounding_box()
                start_x=image_rect['x']+image_rect['width']*.15
                start_y=max(image_rect['y'],viewer_rect['y'])+50
                page.mouse.move(start_x,start_y)
                page.mouse.down()
                page.mouse.move(start_x+100,start_y+100,steps=5)
                page.mouse.up()
                expect(page.locator('#message')).to_contain_text('드래그한 영역')
                page.get_by_role('button',name='확대',exact=True).click()
                assert page.locator('#image-stage').evaluate('(el)=>el.style.width')=='125%'
                page.get_by_role('button',name='수정 초안 저장').click()
                expect(page.locator('#message')).to_contain_text('수정 초안을 저장했습니다')
                page.reload()
                expect(page.locator('#exam option')).to_have_count(2)
                page.locator('#exam').select_option(index=1)
                expect(page.locator('#history option')).to_have_count(2)
                page.locator('#history').select_option(index=1)
                expect(page.locator('.vision-candidate')).to_have_count(2)
                expect(page.locator('.vision-passage').first).to_have_value('Reviewed passage')
                page.get_by_role('button',name='검토 완료 · 문항 저장').click()
                expect(page.locator('#message')).to_contain_text('2개 문항을 저장했습니다')
                expect(page.locator('#questions details')).to_have_count(2)
                assert not errors,errors
                page.screenshot(path=str(tmp_path/'image-review.png'),full_page=True)
                browser.close()
        finally:
            server.terminate();server.wait(timeout=10)
