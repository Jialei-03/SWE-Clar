"""Benchmark-owned capability check; does not import or execute candidate files."""
import json
import platform
import sqlite3
import os
import subprocess
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.request import urlopen
from playwright.sync_api import sync_playwright


class Probe(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b'<button id="probe" onclick="this.textContent=42">probe</button>')
    def log_message(self, *_):
        pass


def preflight():
    with tempfile.TemporaryDirectory() as temp:
        if os.geteuid()==0:
            os.chmod(temp,0o777)
            subprocess.run([sys.executable,'-c',
                'import os,pathlib; assert os.getuid()==1000; assert not os.access("/private",os.R_OK); pathlib.Path("identity.txt").write_text("isolated")'],
                cwd=temp,user=1000,group=1000,extra_groups=[],check=True)
            assert (Path(temp)/'identity.txt').read_text()=='isolated'
            child=subprocess.Popen([sys.executable,'-c','import time; time.sleep(30)'],user=1000,group=1000,extra_groups=[])
            try:
                child.terminate()
                child.wait(timeout=5)
            finally:
                if child.poll() is None:
                    child.kill()
                    child.wait()
        path = Path(temp) / 'probe.sqlite'
        with sqlite3.connect(path) as db:
            db.execute('CREATE TABLE probe(value TEXT)')
            db.execute('INSERT INTO probe VALUES(?)', ('isolated',))
        with sqlite3.connect(path) as db:
            assert db.execute('SELECT value FROM probe').fetchone()[0] == 'isolated'
    server = ThreadingHTTPServer(('127.0.0.1', 0), Probe)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        url = f'http://127.0.0.1:{server.server_port}'
        with urlopen(url, timeout=5) as response:
            assert response.status == 200
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True, args=['--use-angle=swiftshader','--enable-unsafe-swiftshader'])
            try:
                page = browser.new_page()
                page.goto(url)
                page.locator('#probe').click()
                assert page.locator('#probe').inner_text() == '42'
                graphics = page.evaluate("""() => {
                    const c=document.createElement('canvas');c.width=64;c.height=64;
                    const gl=c.getContext('webgl');if(!gl)throw new Error('WebGL unavailable');
                    function shader(type,code){const s=gl.createShader(type);gl.shaderSource(s,code);gl.compileShader(s);if(!gl.getShaderParameter(s,gl.COMPILE_STATUS))throw new Error(gl.getShaderInfoLog(s));return s;}
                    const program=gl.createProgram();gl.attachShader(program,shader(gl.VERTEX_SHADER,'attribute vec3 p;void main(){gl_Position=vec4(p,1.0);}'));
                    gl.attachShader(program,shader(gl.FRAGMENT_SHADER,'precision mediump float;uniform vec3 color;void main(){gl_FragColor=vec4(color,1.0);}'));gl.linkProgram(program);
                    if(!gl.getProgramParameter(program,gl.LINK_STATUS))throw new Error('Shader link failed');gl.useProgram(program);
                    gl.bindBuffer(gl.ARRAY_BUFFER,gl.createBuffer());const location=gl.getAttribLocation(program,'p');gl.enableVertexAttribArray(location);gl.vertexAttribPointer(location,3,gl.FLOAT,false,0,0);
                    gl.enable(gl.DEPTH_TEST);gl.clearColor(0,0,0,1);gl.clear(gl.COLOR_BUFFER_BIT|gl.DEPTH_BUFFER_BIT);
                    function triangle(z,color){gl.bufferData(gl.ARRAY_BUFFER,new Float32Array([-.9,-.9,z,.9,-.9,z,0,.9,z]),gl.STATIC_DRAW);gl.uniform3fv(gl.getUniformLocation(program,'color'),color);gl.drawArrays(gl.TRIANGLES,0,3);}
                    triangle(-.5,[1,0,0]);triangle(.5,[0,0,1]);const pixel=new Uint8Array(4);gl.readPixels(32,32,1,1,gl.RGBA,gl.UNSIGNED_BYTE,pixel);
                    const ext=gl.getExtension('WEBGL_debug_renderer_info');return {pixel:[...pixel],renderer:ext?gl.getParameter(ext.UNMASKED_RENDERER_WEBGL):gl.getParameter(gl.RENDERER),error:gl.getError()};
                }""")
                assert graphics['pixel'] == [255,0,0,255] and graphics['error']==0, graphics
                browser_version = browser.version
            finally:
                browser.close()
    finally:
        server.shutdown()
        worker.join()
        server.server_close()
    return {'passed': True, 'python': platform.python_version(), 'sqlite': sqlite3.sqlite_version,
            'webgl': graphics, 'chromium': browser_version, 'architecture': platform.machine(), 'network': 'loopback-only during execution'}


if __name__ == '__main__':
    print(json.dumps(preflight()))
