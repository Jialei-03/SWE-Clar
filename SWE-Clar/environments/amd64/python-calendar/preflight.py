"""Protected calendar/notification capability check, independent of candidate code."""
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
import json,runpy,threading
from playwright.sync_api import sync_playwright


def preflight():
    base=runpy.run_path('/opt/sweclar/web_preflight.py')['preflight']()
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200);self.send_header('Content-Type','text/javascript' if self.path=='/worker.js' else 'text/html');self.end_headers()
            self.wfile.write(b"self.addEventListener('install',e=>self.skipWaiting());self.addEventListener('activate',e=>e.waitUntil(self.clients.claim()));" if self.path=='/worker.js' else b'<h1>Prepared calendar capability</h1>')
        def log_message(self,*_):pass
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    try:
        with sync_playwright() as p:
            browser=p.chromium.launch(channel='chromium',headless=True)
            try:
                context=browser.new_context(permissions=['notifications'],timezone_id='UTC');page=context.new_page();page.goto(f'http://127.0.0.1:{server.server_port}')
                result=page.evaluate('''async()=>{await navigator.serviceWorker.register('/worker.js');const r=await navigator.serviceWorker.ready;await r.showNotification('Prepared notification',{body:'Synthetic capability test',tag:'calendar-preflight'});const ns=await r.getNotifications();const out=ns.map(n=>({title:n.title,body:n.body,tag:n.tag}));ns.forEach(n=>n.close());return {permission:Notification.permission,notifications:out};}''')
                assert result=={'permission':'granted','notifications':[{'title':'Prepared notification','body':'Synthetic capability test','tag':'calendar-preflight'}]}
                context.close()
            finally:browser.close()
    finally:server.shutdown();server.server_close();thread.join(timeout=5)
    return {**base,'passed':True,'chromium_channel':'chromium','service_worker_notifications':True,'notification_delivery':'Actual browser notification service; permission granted before evaluation'}


if __name__=='__main__':print(json.dumps(preflight()))
