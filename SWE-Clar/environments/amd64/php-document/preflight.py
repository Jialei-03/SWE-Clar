"""Protected PHP, database, browser, font, image, PDF and decoder capability check."""
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import socket
import subprocess
import tempfile
import time
from urllib.request import urlopen

import pypdf
import pypdfium2
from PIL import Image
import zxingcpp
from playwright.sync_api import sync_playwright


def preflight():
    module_spec=importlib.util.spec_from_file_location('web_preflight','/opt/sweclar/web_preflight.py')
    web=importlib.util.module_from_spec(module_spec); module_spec.loader.exec_module(web)
    result={'web':web.preflight()}
    child={'user':1000,'group':1000,'extra_groups':[]} if os.geteuid()==0 else {}
    with tempfile.TemporaryDirectory(prefix='php-health-') as temp:
        os.chmod(temp,0o777)
        process=subprocess.run(['php','/opt/sweclar/document_probe.php',temp],capture_output=True,text=True,check=True,timeout=30,**child)
        result['php']=json.loads(process.stdout)
        assert result['php']['php']=='8.3.28' and all(result['php'][x] for x in ['bcmath','gd','mbstring'])
        pdf_bytes=(Path(temp)/'probe.pdf').read_bytes()
        document=pypdf.PdfReader(io.BytesIO(pdf_bytes));assert len(document.pages)==2
        for page in document.pages:
            assert abs(float(page.mediabox.width)-210*72/25.4)<0.01
            assert abs(float(page.mediabox.height)-148*72/25.4)<0.01
            text=page.extract_text();assert 'SAMPLE / NOT VALID' in text and text.count('W')==480
            assert len(page.images)>=1
        raster=pypdfium2.PdfDocument(pdf_bytes)
        bitmap=raster[1].render(scale=3);im=bitmap.to_pil().copy()
        codes=zxingcpp.read_barcodes(im)
        assert any(x.bytes=='SYN-REF-é-001'.encode() and x.format==zxingcpp.BarcodeFormat.PDF417 for x in codes)
        result['pdf']={'pages':2,'pdf417_utf8_roundtrip':True,'wrapped_ascii_characters_per_page':480,'rendered_pixels':list(im.size),'embedded_png':True}
        png=io.BytesIO();Image.new('RGB',(37,23),(16,80,160)).save(png,format='PNG');data=png.getvalue()
        with socket.socket() as sock:
            sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
        server=subprocess.Popen(['php','-S',f'127.0.0.1:{port}','/opt/sweclar/document_probe.php'],cwd=temp,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,**child)
        try:
            url=f'http://127.0.0.1:{port}/'
            for _ in range(100):
                if server.poll() is not None:raise RuntimeError('PHP HTTP server exited')
                try:
                    with urlopen(url,timeout=0.2):break
                except OSError:time.sleep(0.05)
            else:raise RuntimeError('PHP HTTP server not ready')
            with sync_playwright() as p:
                browser=p.chromium.launch(headless=True)
                try:
                    page=browser.new_page();page.goto(url)
                    page.locator('input[type=file]').set_input_files({'name':'probe.png','mimeType':'image/png','buffer':data})
                    with page.expect_navigation():page.get_by_role('button',name='Upload').click()
                    uploaded=json.loads(page.locator('body').inner_text())
                    assert uploaded=={'session':'synthetic-session','width':37,'height':23,'sha256':hashlib.sha256(data).hexdigest()}
                    result['php_browser']={'session_cookie':True,'multipart_png_upload':True,'gd_pixel_dimensions':[37,23]}
                finally:browser.close()
        finally:
            server.terminate()
            try:server.wait(timeout=5)
            except subprocess.TimeoutExpired:server.kill();server.wait()
    result['passed']=True
    return result


if __name__=='__main__':print(json.dumps(preflight()))
