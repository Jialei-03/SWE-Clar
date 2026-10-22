"""Visible directory and nonconflicting receipt regression only."""
import base64
from io import BytesIO
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parent))
from PIL import Image, PngImagePlugin
from playwright.sync_api import expect
from loyalty_support import Application,browser_session,request


def login(page,app,username):
    user=next(u for u in app.seed['users'] if u['username']==username)
    page.goto(app.url);page.locator('#username').fill(username);page.locator('#password').fill(user['password']);page.locator('#login').click()
    expect(page.locator('#workspace')).to_be_visible()


def token(app,name):
    user=next(u for u in app.seed['users'] if u['username']==name)
    response=request(app,'/api/login',{'username':name,'password':user['password']})
    assert response['status']==200
    return response['body']['token']


def png():
    image=Image.new('RGBA',(7,5),(31,101,211,133));output=BytesIO();meta=PngImagePlugin.PngInfo();meta.add_text('Comment','synthetic discarded metadata')
    image.save(output,format='PNG',pnginfo=meta)
    return output.getvalue(),image.tobytes()


def run():
    with Application() as app,browser_session() as browser:
        admin=token(app,'admin');consumer=token(app,'consumer-a');other=token(app,'consumer-b')
        assert request(app,'/api/malls',{'id':'bad','name':'bad'},token=consumer)['status']==403
        assert request(app,'/api/malls',b'{',token=consumer)['status']==403
        assert request(app,'/api/malls',b'{')['status']==401
        assert request(app,'/api/malls',b'{',token=admin)['status']==400
        owners=request(app,'/api/merchant-owners',token=admin)
        assert owners['status']==200 and any(row['id']=='merchant-new' for row in owners['body']['merchant_owners'])
        assert request(app,'/api/merchant-owners',token=consumer)['status']==403
        page=browser.new_page(viewport={'width':390,'height':844});login(page,app,'admin')
        page.locator('#mall-id').fill('mall / 雨');page.locator('#mall-name').fill('  <b>Synthetic</b>  ');page.locator('#create-mall').click()
        expect(page.locator('[data-mall-id="mall / 雨"]')).to_contain_text('<b>Synthetic</b>')
        page.locator('#shop-id').fill('new-shop');page.locator('#shop-name').fill('Synthetic New Shop');page.locator('#shop-owner').select_option('merchant-new');page.locator('#create-shop').click()
        expect(page.locator('[data-shop-id="new-shop"]')).to_be_visible()
        page.locator('#branch-id').fill('new-branch');page.locator('#branch-shop').select_option('new-shop');page.locator('#branch-mall').select_option('mall / 雨');page.locator('#branch-participating').check();page.locator('#create-branch').click()
        expect(page.locator('[data-branch-id="new-branch"]')).to_be_visible()
        page.locator('#logout').click();expect(page.locator('#workspace')).to_be_hidden()
        login(page,app,'consumer-a');raw,pixels=png()
        page.locator('#upload-file').set_input_files({'name':'synthetic.png','mimeType':'image/png','buffer':raw});page.locator('#upload-photo').click()
        expect(page.locator('#assets [data-asset-id]')).to_have_count(1)
        page.wait_for_function("document.querySelector('#assets img')?.naturalWidth === 7 || !!document.querySelector('#assets canvas')")
        assets=request(app,'/api/assets',token=consumer)['body']['assets'];asset=assets[0]
        assert request(app,asset['url'],token=other,raw=True)['status']==404
        assert request(app,asset['url'],token=admin,raw=True)['status']==404
        image_response=request(app,asset['url'],token=consumer,raw=True);image=Image.open(BytesIO(image_response['body']));image.load()
        assert image.convert('RGBA').tobytes()==pixels and not image.info
        page.locator('#receipt-key').fill('visible-key');page.locator('#receipt-branch').select_option('new-branch');page.locator('#receipt-number').fill(' R-01 ');page.locator('#receipt-date').fill('2024-02-29');page.locator('#receipt-amount').fill('999');page.locator('#submit-receipt').click()
        expect(page.locator('[data-receipt-id]')).to_have_count(1)
        receipt=request(app,'/api/receipts',token=consumer)['body']['receipts'][0]
        assert receipt['status']=='pending' and receipt['points']==0 and receipt['reviewed_by'] is None and receipt['receipt_number']=='R-01'
        assert request(app,'/api/wallet',token=consumer)['body']['balance']==0
        assert request(app,asset['url'],token=admin,raw=True)['body']==image_response['body']
        for width,height in [(390,844),(1280,900)]:
            page.set_viewport_size({'width':width,'height':height});assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1')
        page.locator('#logout').click();expect(page.locator('#workspace')).to_be_hidden();assert page.locator('#receipt-key').input_value()==''
        login(page,app,'admin');expect(page.locator('[data-receipt-id]')).to_have_count(1)
        expect(page.locator('[data-approve]')).to_be_visible();expect(page.locator('[data-reject]')).to_be_visible()
        app.stop();app.start()
        assert request(app,'/api/catalog',token=admin)['status']==401
        consumer=token(app,'consumer-a')
        assert request(app,'/api/receipts',token=consumer)['body']['receipts']==[receipt]
        assert request(app,asset['url'],token=consumer,raw=True)['body']==image_response['body']
    return {'passed':True,'scope':'Visible role directory and actual nonconflicting pending receipt only'}

if __name__=='__main__':print(json.dumps(run()))
