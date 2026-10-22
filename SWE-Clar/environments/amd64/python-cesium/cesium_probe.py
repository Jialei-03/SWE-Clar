import os,json,threading,http.server,functools
from playwright.sync_api import sync_playwright
assert os.getuid()==1000
server=http.server.ThreadingHTTPServer(('127.0.0.1',0),functools.partial(http.server.SimpleHTTPRequestHandler,directory='/opt/sweclar/cesium/Build/Cesium'))
threading.Thread(target=server.serve_forever,daemon=True).start()
with sync_playwright() as p:
 b=p.chromium.launch(headless=True,args=['--use-angle=swiftshader','--enable-unsafe-swiftshader'],env={'PATH':'/usr/local/bin:/usr/bin:/bin','HOME':'/tmp'})
 page=b.new_page();page.goto('http://127.0.0.1:'+str(server.server_port));page.add_style_tag(url='/Widgets/widgets.css');page.add_script_tag(url='/Cesium.js')
 result=page.evaluate("""async()=>{document.body.innerHTML='<div id="map" style="width:640px;height:480px"></div>';const v=new Cesium.Viewer('map',{baseLayer:false,geocoder:false,baseLayerPicker:false,animation:false,timeline:false,skyBox:false,skyAtmosphere:false});v.entities.add({position:Cesium.Cartesian3.fromDegrees(0,0),point:{pixelSize:18,color:Cesium.Color.ORANGE,disableDepthTestDistance:Infinity}});v.camera.setView({destination:Cesium.Cartesian3.fromDegrees(0,0,20000),orientation:{heading:0,pitch:-Math.PI/2,roll:0}});await new Promise(r=>{const off=v.scene.postRender.addEventListener(()=>{off();r()});v.scene.requestRender()});await new Promise(r=>setTimeout(r,500));let hit;for(let i=0;i<60&&!hit;i++){await new Promise(r=>setTimeout(r,100));hit=v.scene.pick(new Cesium.Cartesian2(v.canvas.clientWidth/2,v.canvas.clientHeight/2));}return{version:Cesium.VERSION,width:v.canvas.width,height:v.canvas.height,picked:!!hit}}""")
 assert result['version']=='1.121' and result['picked'],result
 b.close()
server.shutdown();print(json.dumps({'passed':True,'uid':os.getuid(),'actual_webgl':result}))
