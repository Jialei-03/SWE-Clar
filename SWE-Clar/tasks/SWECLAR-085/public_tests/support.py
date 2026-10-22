import os, socket, subprocess, time, urllib.request
from contextlib import contextmanager
from pathlib import Path
from playwright.sync_api import sync_playwright
from browser_isolation import launch

def drop():
    if os.getuid()==0:os.setgroups([]);os.setgid(1000);os.setuid(1000)
@contextmanager
def application():
    with socket.socket() as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
    process=subprocess.Popen(['python','server.py'],cwd=os.environ.get('SWECLAR_PROJECT_DIR','/workspace'),env={'PATH':os.environ['PATH'],'HOME':'/tmp','PORT':str(port),'PYTHONDONTWRITEBYTECODE':'1'},preexec_fn=drop,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
    url=f'http://127.0.0.1:{port}'
    try:
        for _ in range(100):
            try:urllib.request.urlopen(url,timeout=.2);break
            except OSError:time.sleep(.05)
        else:raise RuntimeError('Application did not start')
        with sync_playwright() as driver:
            browser=launch(driver.chromium,headless=True,args=['--autoplay-policy=no-user-gesture-required'])
            try:
                page=browser.new_page();page.goto(url);page.wait_for_selector('#recent [data-id]');page.wait_for_selector('#schedule [data-id]');yield page
            finally:browser.close()
    finally:process.terminate();process.wait(timeout=5)

def play(page,section='schedule'):
    page.locator('#'+section+' [data-id]').first.click()
    page.wait_for_function("!document.querySelector('audio').paused && !document.querySelector('audio').seeking && document.querySelector('audio').readyState >= 2 && document.querySelector('audio').currentTime > 0.15")
