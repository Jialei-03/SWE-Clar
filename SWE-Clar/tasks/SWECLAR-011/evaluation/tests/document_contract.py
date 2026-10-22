"""Five independent RU gates against the frozen synthetic document web-app contract."""
import sys as _browser_sys
_browser_sys.path.insert(0, '/public_tests')
from browser_isolation import launch as _isolated_browser_launch
from concurrent.futures import ThreadPoolExecutor
import hashlib,io,json,os,re,sys,time,traceback,unicodedata
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
from document_support import application,Client,CandidateFailure,persisted,state_digest,corrupt_stored_asset
from pdf_checks import PDF,MM,compact,pixel,near,assert_slot,pattern
from PIL import Image
from playwright.sync_api import sync_playwright,expect,TimeoutError as BrowserTimeout

FIELDS=['document_id','name','group','contact','reviewer','reference']
VALUES={'document_id':'TEST-ID-31','name':'Équipe synthétique','group':'Groupe Exemple','contact':'fiction@example.test','reviewer':'فريق تجريبي','reference':'REF-é-اختبار-31'}

def profile(c,id='testing',values=None):
    values=values or dict(VALUES);c.call('/profiles','POST',{'id':id,'values':values},201);return values

def render(c,name='result.pdf',kind='sample_card',id='testing'):
    result=c.call('/render','POST',{'profile_id':id,'kind':kind,'filename':name},201)['document'];data,headers=c.call('/documents/'+name,raw=True)
    assert headers.get('Content-Type','').startswith('application/pdf')
    assert name in headers.get('Content-Disposition','') and 'attachment' in headers.get('Content-Disposition','')
    assert result['bytes']==len(data) and result['sha256']==hashlib.sha256(data).hexdigest(),'Export metadata did not describe actual downloaded bytes'
    assert result['profile_id']==id and result['kind']==kind and result['filename']==name
    return data,result

def patch(c,field,values,revision=None,status=200):
    if revision is None:revision=c.call('/template')['revision']
    return c.call('/template/fields/'+field,'PATCH',{'expected_revision':revision,'values':values},status)

def place(c,slot,id,revision=None,status=200):
    if revision is None:revision=c.call('/template')['revision']
    return c.call('/template/placements/'+slot,'PUT',{'expected_revision':revision,'asset_id':id},status)

def events(c):return c.call('/audit')['events']

def login_page(page,app,user='admin-a'):
    page.goto(app.url);page.get_by_label('Username',exact=True).fill(user);page.get_by_label('Password',exact=True).fill('demo-pass');page.get_by_role('button',name='Sign in',exact=True).click();expect(page.get_by_label('Saved profile',exact=True)).to_be_visible();expect(page.get_by_label('Saved profile',exact=True).locator('option[value=sample-one]')).to_have_count(1);page.get_by_label('Saved profile',exact=True).select_option('sample-one')

def check_1():
    with application() as app:
        nobody=Client(app)
        for path in ['/session','/profiles','/template','/assets','/documents','/audit']:nobody.call(path,status=401)
        nobody.call('/login','POST',{'username':'admin-a','password':'bad'},401)
        one=Client(app,'admin-a');editor=Client(app,'editor-a')
        cookies=list(one.cookies);assert len(cookies)==1 and cookies[0].name=='document_session' and len(cookies[0].value)>=24
        assert cookies[0].has_nonstandard_attr('HttpOnly') and cookies[0].get_nonstandard_attr('SameSite')=='Strict'
        for c,id in [(one,'admin-a'),(editor,'editor-a')]:
            user=c.call('/session')['user'];assert user['id']==id and not any(k in user for k in ['password','token','password_hash'])
        values=profile(editor);values['name']='W'*160;editor.call('/profiles/testing','PUT',{'values':values})
        for invalid in ['', ' '*3, 'é'*81, 'A\nB', '\x00', '中', '😀', 1, True, None]:
            before=state_digest(app);editor.call('/profiles/testing','PUT',{'values':dict(values,name=invalid)},400);assert state_digest(app)==before,'Invalid profile modified persisted state'
        editor.call('/profiles','POST',{'id':'testing','values':values},409)
        for id in ['../escape','https://external.invalid','Upper','', 'x'*41]:editor.call('/profiles','POST',{'id':id,'values':values},400)
        profiles=one.call('/profiles')['profiles'];assert [x['id'] for x in profiles]==sorted(x['id'] for x in profiles)
        assert next(x for x in profiles if x['id']=='testing')['values']==values
        app.stop();app.start();assert editor.call('/session')['user']['id']=='editor-a';assert one.call('/profiles')['profiles']==profiles
        token=cookies[0].value;one.call('/logout','POST',{});one.call('/profiles',status=401)
        nobody.call('/profiles',status=401,headers={'Cookie':'document_session='+token,'X-Actor-Id':'admin-a','X-Role':'admin'})
        with sync_playwright() as p:
            browser=_isolated_browser_launch(p.chromium, headless=True)
            try:
                page=browser.new_page();login_page(page,app,'editor-a');page.get_by_label('Full name',exact=True).fill('Browser <safe> label');page.get_by_role('button',name='Save profile',exact=True).click();expect(page.get_by_role('status')).to_contain_text('saved')
                page.reload();expect(page.get_by_label('Full name',exact=True)).to_have_value('Browser <safe> label')
                page.get_by_role('button',name='Log out',exact=True).click();expect(page.get_by_role('button',name='Sign in',exact=True)).to_be_visible()
            finally:browser.close()

def check_2():
    with application() as app:
        c=Client(app,'admin-a');values=profile(c)
        for kind in ['sample_card','sample_pass']:
            data,meta=render(c,kind+'.pdf',kind);pdf=PDF(data)
            try:
                pdf.content(values)
                for i,key in enumerate(FIELDS):assert pdf.field_contains(i//3,i%3,values[key]),f'Field {key} escaped its public panel'
                for side in range(2):
                    glyphs=pdf.glyphs(side)
                    assert all(-.5<=g['box'][0]<=g['box'][2]<=210*MM+.5 and -.5<=g['box'][1]<=g['box'][3]<=148*MM+.5 for g in glyphs),'Text outside document'
                assert persisted(app,data),'PDF did not persist as actual bytes'
            finally:pdf.close()
        long=dict(zip(FIELDS,['W'*160,'Á'*80,'د'*80,'M'*160,'Révision étendue','REF-long-23']))
        profile(c,'long',long);data,_=render(c,'long.pdf',id='long');pdf=PDF(data)
        try:
            pdf.content(long)
            for i,key in enumerate(FIELDS):assert pdf.field_contains(i//3,i%3,long[key]),f'Long {key} clipped or overflowed its panel'
        finally:pdf.close()
        for name in ['../x.pdf','x/y.pdf','x.pdf.exe','x.pdf\n','é.pdf','a'*65+'.pdf']:
            c.call('/render','POST',{'profile_id':'testing','kind':'sample_card','filename':name},400)
        before=c.call('/documents')['documents'];app.stop();app.start();assert c.call('/documents')['documents']==before
        with sync_playwright() as p:
            browser=_isolated_browser_launch(p.chromium, headless=True)
            try:
                page=browser.new_page();login_page(page,app);page.get_by_label('PDF filename',exact=True).fill('browser.pdf');page.get_by_role('button',name='Generate PDF',exact=True).click();link=page.get_by_role('link',name='Download browser.pdf',exact=True);expect(link).to_be_visible()
                with page.expect_download() as info:link.click()
                data=Path(info.value.path()).read_bytes();pdf=PDF(data)
                try:pdf.content(next(x['values'] for x in c.call('/profiles')['profiles'] if x['id']=='sample-one'))
                finally:pdf.close()
                assert persisted(app,data)
            finally:browser.close()

def check_3():
    with application() as app:
        c=Client(app,'admin-a');second=Client(app,'admin-b');editor=Client(app,'editor-a');values=profile(c);values['name']='Typography-Sample';c.call('/profiles/testing','PUT',{'values':values})
        t=c.call('/template');assert t['revision']==0
        for field in FIELDS:assert t['styles'][field]=={'color':'#000000','background':None,'font_size':10,'weight':'normal','border':False,'visible':True}
        before=state_digest(app)
        editor.call('/template/fields/name','PATCH',{'expected_revision':0,'values':{'color':'#123456'},'role':'admin','actor_id':'admin-a'},403,headers={'X-Role':'admin'})
        editor.upload(pattern(),status=403);place(editor,'front_left',None,0,403);assert state_digest(app)==before
        for revision in [None,True,1.5,-1,'0']:
            c.call('/template/fields/name','PATCH',{'expected_revision':revision,'values':{'visible':False}},400)
        for invalid in [{},{'unknown':1},{'color':'red'},{'color':None},{'background':False},{'font_size':5},{'font_size':13},{'font_size':10.5},{'font_size':True},{'weight':'heavy'},{'border':1},{'visible':'false'},{'color':'#112233','font_size':99}]:
            before=state_digest(app);patch(c,'name',invalid,status=400);assert state_digest(app)==before,'Invalid style partially applied'
        patch(c,'not-a-field',{'visible':False},status=400)
        t=patch(c,'name',{'color':'#7f193b','background':'#E3D6A8','font_size':12,'weight':'bold','border':True});assert t['revision']==1 and t['styles']['name']['color']=='#7F193B'
        before=state_digest(app);patch(c,'name',{'color':'#7F193B'});assert state_digest(app)==before,'No-op created mutation or audit'
        patch(c,'name',{'color':'#7f193b'},revision=0,status=409)
        t=patch(c,'group',{'visible':False});assert t['revision']==2 and t['styles']['name']['font_size']==12
        data,_=render(c);pdf=PDF(data)
        try:
            pdf.content(values,hidden=['group']);assert 'Groupe' not in pdf.texts[0] and compact('المجموعة') not in compact(pdf.texts[0])
            glyphs=[g for g in pdf.glyphs(0) if (148-83)*MM<g['box'][1]<(148-59)*MM]
            assert len(glyphs)>=len('Typography-Sample') and all(abs(g['size']-12)<.1 for g in glyphs),'Configured point size ignored'
            assert all(near(g['color'][:3],(127,25,59),1) for g in glyphs),'Configured actual PDF text color ignored'
            image=pdf.raster(0);bold_ink=field_ink(image);assert near(pixel(image,190,70),(227,214,168)),'Panel background ignored'
            assert near(pixel(image,10,65),(0,0,0),50),'Panel border ignored'
        finally:pdf.close()
        patch(c,'name',{'weight':'normal'});normal,_=render(c,'normal-weight.pdf');normal_pdf=PDF(normal)
        try:assert bold_ink>field_ink(normal_pdf.raster(0))*1.10,'Bold and normal did not produce distinct real stroke weights'
        finally:normal_pdf.close()
        t=patch(c,'name',{'background':None,'border':False,'font_size':6,'weight':'normal'});assert t['styles']['name']['color']=='#7F193B'
        data,_=render(c,'transparent.pdf');pdf=PDF(data)
        try:
            assert near(pixel(pdf.raster(0),190,70),(255,255,255))
            small=[g for g in pdf.glyphs(0) if (148-83)*MM<g['box'][1]<(148-59)*MM]
            assert small and all(abs(g['size']-6)<.1 for g in small),'Minimum valid point size ignored'
        finally:pdf.close()
        revision=t['revision']
        def race(client):
            try:return client.call('/template/fields/contact','PATCH',{'expected_revision':revision,'values':{'color':'#234567'}})['revision']
            except CandidateFailure as e:
                assert 'got 409' in str(e);return 'conflict'
        with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(race,[c,second]))
        assert sorted(map(str,results))==sorted([str(revision+1),'conflict']),'Same-version writes both applied'
        saved=c.call('/template');app.stop();app.start();assert c.call('/template')==saved
        browser_styles(app,c)

def field_ink(image):
    box=(round(10/210*image.width),round(59/148*image.height),round(200/210*image.width),round(83/148*image.height))
    return sum(1 for r,g,b in image.crop(box).getdata() if r<180 and g<90 and b<130)

def browser_styles(app,c):
    with sync_playwright() as p:
        browser=_isolated_browser_launch(p.chromium, headless=True)
        try:
            page=browser.new_page();login_page(page,app);page.get_by_label('Field',exact=True).select_option('name');page.get_by_label('Text color',exact=True).fill('#336699')
            patch(c,'name',{'color':'#DD5500'})
            page.get_by_role('button',name='Save field settings',exact=True).click();expect(page.get_by_role('status')).to_contain_text(re.compile('changed|conflict',re.I));expect(page.get_by_label('Text color',exact=True)).to_have_value('#336699')
            assert c.call('/template')['styles']['name']['color']=='#DD5500'
            page.get_by_role('button',name='Save field settings',exact=True).click();expect(page.get_by_role('status')).to_contain_text('saved');assert c.call('/template')['styles']['name']['color']=='#336699'
            page.reload();page.get_by_label('Field',exact=True).select_option('name');expect(page.get_by_label('Text color',exact=True)).to_have_value('#336699')
        finally:browser.close()

def padded_png(data,size):
    import struct,zlib
    length=size-len(data)-12;assert length>=8
    chunk=b'tEXt'+b'Comment\0'+b'A'*(length-8)
    return data[:-12]+struct.pack('!I',length)+chunk+struct.pack('!I',zlib.crc32(chunk))+data[-12:]

def check_4():
    with application() as app:
        c=Client(app,'admin-a');values=profile(c)
        image=pattern();a=c.upload(image)['asset'];assert a['sha256']==hashlib.sha256(image).hexdigest() and [a['width'],a['height']]==[80,40]
        downloaded,headers=c.call('/assets/'+a['id'],raw=True);assert downloaded==image and headers['Content-Type'].startswith('image/png');assert persisted(app,image)
        repeated=c.upload(image,filename='../../ignored.png')['asset'];assert repeated['id']!=a['id']
        limits=[pattern((8,8)),pattern((1024,8)),pattern((8,1024)),padded_png(image,262144)]
        for data in limits:c.upload(data)
        jpg=io.BytesIO();Image.new('RGB',(16,16),(0,0,0)).save(jpg,format='JPEG')
        for invalid in [b'not-image',image[:-5],jpg.getvalue(),pattern((7,8)),pattern((8,7)),pattern((1025,8)),pattern((8,1025)),padded_png(image,262145)]:
            before=state_digest(app);c.upload(invalid,status=400);assert state_digest(app)==before,'Rejected upload persisted data or audit'
        for slot,id in [('unknown',a['id']),('back','unknown'),('back','../../arbitrary'),('back',False)]:
            before=state_digest(app);place(c,slot,id,status=400);assert state_digest(app)==before
        for slot in ['front_left','front_right','back','watermark']:place(c,slot,a['id'])
        colors=((220,30,50),(20,170,70),(35,70,215),(230,190,25))
        for kind in ['sample_card','sample_pass']:
            data,_=render(c,kind+'.pdf',kind);pdf=PDF(data)
            try:
                pdf.content(values);pdf.barcode(values['reference']);images=[pdf.raster(i) for i in range(2)]
                assert_slot(images[0],(10,5,20,18),(80,40),colors);assert_slot(images[0],(180,5,20,18),(80,40),colors);assert_slot(images[1],(180,5,20,18),(80,40),colors)
                for side in range(2):
                    for (x,y),color in zip([(82.5,58.75),(127.5,58.75),(82.5,81.25),(127.5,81.25)],colors):
                        expected=tuple(round(channel*.15+255*.85) for channel in color) if kind=='sample_pass' else (255,255,255)
                        assert near(pixel(images[side],x,y),expected,6),'Watermark wrong kind, opacity, page, content or position'
            finally:pdf.close()
        original,_=c.call('/documents/sample_pass.pdf',raw=True)
        other_colors=((12,80,180),(210,90,15),(120,35,150),(25,180,170));other=pattern((32,64),other_colors);other_id=c.upload(other)['asset']['id'];place(c,'front_left',other_id);place(c,'front_right',None);place(c,'watermark',None)
        data,_=render(c,'replaced.pdf','sample_pass');pdf=PDF(data)
        try:
            assert_slot(pdf.raster(0),(10,5,20,18),(32,64),other_colors);assert near(pixel(pdf.raster(0),190,14),(255,255,255))
            assert near(pixel(pdf.raster(1),127.5,81.25),(255,255,255))
        finally:pdf.close()
        assert c.call('/documents/sample_pass.pdf',raw=True)[0]==original,'New configuration mutated an existing export'
        patch(c,'reference',{'visible':False});data,_=render(c,'hidden-reference.pdf');pdf=PDF(data)
        try:pdf.content(values,hidden=['reference']);pdf.barcode(values['reference'])
        finally:pdf.close()
        values['reference']='ق'*80;values['name']='W'*120;c.call('/profiles/testing','PUT',{'values':values});place(c,'watermark',a['id']);data,_=render(c,'long-reference.pdf','sample_pass');pdf=PDF(data)
        try:
            pdf.barcode(values['reference']);im=pdf.raster(0)
            overlap=[g for g in pdf.glyphs(0) if g['character']=='W' and 75*MM<g['box'][0]<135*MM and (148-90)*MM<g['box'][1]<(148-59)*MM]
            assert len(overlap)>=3,'Expected visible foreground text over watermark'
            for g in overlap[:5]:
                x1,y1,x2,y2=g['box'];box=(round(x1/(210*MM)*im.width),round((148*MM-y2)/(148*MM)*im.height),round(x2/(210*MM)*im.width)+1,round((148*MM-y1)/(148*MM)*im.height)+1)
                assert min(sum(px) for px in im.crop(box).getdata())<20,'Watermark overpainted foreground glyphs'
        finally:pdf.close()
        current=c.call('/template');app.stop();app.start();assert c.call('/template')==current and c.call('/assets/'+other_id,raw=True)[0]==other
        browser_assets(app,c)

def browser_assets(app,c):
    with sync_playwright() as p:
        browser=_isolated_browser_launch(p.chromium, headless=True)
        try:
            page=browser.new_page();login_page(page,app);before={x['id'] for x in c.call('/assets')['assets']};data=pattern((24,16))
            page.get_by_label('PNG image',exact=True).set_input_files({'name':'browser.png','mimeType':'image/png','buffer':data});page.get_by_role('button',name='Upload image',exact=True).click();expect(page.get_by_role('status')).to_contain_text('uploaded')
            new=[x for x in c.call('/assets')['assets'] if x['id'] not in before];assert len(new)==1 and new[0]['sha256']==hashlib.sha256(data).hexdigest()
            expect(page.get_by_role('img',name='Uploaded image '+new[0]['id'],exact=True)).to_be_visible()
            page.get_by_label('Image slot',exact=True).select_option('back');page.get_by_label('Placed image',exact=True).select_option(new[0]['id']);page.get_by_role('button',name='Save placement',exact=True).click();expect(page.get_by_role('status')).to_contain_text('saved');assert c.call('/template')['placements']['back']==new[0]['id']
            page.reload();page.get_by_label('Image slot',exact=True).select_option('back');expect(page.get_by_label('Placed image',exact=True)).to_have_value(new[0]['id'])
        finally:browser.close()

def check_5():
    with application() as app:
        c=Client(app,'admin-a');other=Client(app,'admin-b');editor=Client(app,'editor-a');values=profile(c);assert events(c)==[]
        begin=int(time.time())
        t=c.call('/template/fields/name','PATCH',{'expected_revision':0,'values':{'font_size':11},'actor_id':'editor-a','timestamp':0,'type':'forged'})
        image=pattern();aid=other.upload(image)['asset']['id'];t=place(other,'watermark',aid);data,meta=render(editor,'kept.pdf','sample_pass')
        audit=events(c);expected=[('admin-a','configure_field','name',1),('admin-b','upload_asset',aid,1),('admin-b','place_asset','watermark',2),('editor-a','render','kept.pdf',2)]
        assert [(e['actor_id'],e['type'],e['target'],e['revision']) for e in audit]==expected,'Audit attribution/target/revision disagrees with committed actions'
        ids=[e['id'] for e in audit];assert all(type(i)is int for i in ids) and ids==sorted(set(ids))
        assert all(type(e['timestamp'])is int and begin<=e['timestamp']<=int(time.time()) for e in audit),'Audit clock is not trusted commit time'
        assert meta['revision']==2
        before=state_digest(app)
        for request in [{'profile_id':'testing','kind':'unknown','filename':'kept.pdf'},{'profile_id':'testing','kind':'sample_pass','filename':'../kept.pdf'}]:c.call('/render','POST',request,400)
        c.call('/render','POST',{'profile_id':'missing','kind':'sample_pass','filename':'kept.pdf'},404)
        patch(c,'name',{'font_size':11});place(c,'watermark',aid);patch(c,'name',{'visible':False},revision=0,status=409)
        assert state_digest(app)==before and c.call('/documents/kept.pdf',raw=True)[0]==data,'Read/rejection/no-op changed document state or audit'
        values['name']='Updated synthetic member';c.call('/profiles/testing','PUT',{'values':values});assert c.call('/documents/kept.pdf',raw=True)[0]==data
        new,meta=render(c,'kept.pdf','sample_pass');assert new!=data and events(c)[-1]['actor_id']=='admin-a' and len(events(c))==5
        assert persisted(app,new),'Replacement PDF not actually persisted'
        snapshot=events(c);app.stop();app.start();assert events(c)==snapshot and c.call('/documents/kept.pdf',raw=True)[0]==new
        # Corrupt an evaluator-created stored upload, then verify failure preserves published output.
        app.stop();corrupt_stored_asset(app,image);app.start();before=state_digest(app)
        result=c.call('/render','POST',{'profile_id':'testing','kind':'sample_pass','filename':'kept.pdf'},422);assert result['error']['code']=='asset_unavailable'
        assert c.call('/documents/kept.pdf',raw=True)[0]==new and state_digest(app)==before,'Failed backing-asset render changed output, metadata, audit or left temporary files'
    storage_failure()
    audit_failure()

def storage_failure():
    with application() as app:
        c=Client(app,'admin-a');profile(c);original,_=render(c,'kept.pdf');app.stop()
        # A normal candidate UID owns this isolated application data; the manager
        # simulates a read-only backing store without touching benchmark files.
        app.script("import os,pathlib,sys,json;p=pathlib.Path(sys.argv[1]);saved={str(x):x.stat().st_mode&0o777 for x in [p,*p.rglob('*')]};print(json.dumps(saved));[(os.chmod(x,0o555 if x.is_dir() else 0o444)) for x in [p,*p.rglob('*')]]")
        try:
            app.start();before=state_digest(app);result=c.call('/render','POST',{'profile_id':'testing','kind':'sample_card','filename':'kept.pdf'},500);assert result['error']['code']=='render_failed'
            assert c.call('/documents/kept.pdf',raw=True)[0]==original and state_digest(app)==before,'Read-only storage failure partially published'
        finally:
            app.stop();app.script("import os,pathlib,sys;p=pathlib.Path(sys.argv[1]);[(os.chmod(x,0o755 if x.is_dir() else 0o644)) for x in [p,*p.rglob('*')]]")


TABLE_SNAPSHOT = '''import pathlib,sqlite3,sys,json,hashlib
root=pathlib.Path(sys.argv[1]);out=[]
for p in root.rglob('*'):
 if not p.is_file():continue
 with p.open('rb') as f:header=f.read(16)
 if header!=b'SQLite format 3\\x00':continue
 db=sqlite3.connect('file:'+str(p)+'?mode=ro',uri=True)
 for (table,) in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'").fetchall():
  quoted='"'+table.replace('"','""')+'"'
  rows=sorted(repr(row) for row in db.execute('SELECT * FROM '+quoted))
  out.append([str(p.relative_to(root)),table,hashlib.sha256(repr(rows).encode()).hexdigest()])
 db.close()
print(json.dumps(out))'''

TABLE_FAULT = '''import pathlib,sqlite3,sys,json
relative,table=json.loads(sys.argv[2]);enabled=json.loads(sys.argv[3])
db=sqlite3.connect(str(pathlib.Path(sys.argv[1])/relative));quoted='"'+table.replace('"','""')+'"'
for operation in ['INSERT','UPDATE','DELETE']:
 name='evaluator_render_fault_'+operation
 db.execute('DROP TRIGGER IF EXISTS '+name)
 if enabled:db.execute('CREATE TRIGGER '+name+' BEFORE '+operation+' ON '+quoted+" BEGIN SELECT RAISE(ABORT,'synthetic render commit fault'); END")
db.commit();db.close()'''

def audit_failure():
    with application() as app:
        c=Client(app,'admin-a');values=profile(c);render(c,'kept.pdf')
        values['name']='A distinct newly rendered value';c.call('/profiles/testing','PUT',{'values':values})
        before_tables={(p,t):digest for p,t,digest in json.loads(app.script(TABLE_SNAPSHOT))}
        original,_=render(c,'kept.pdf')
        after_tables={(p,t):digest for p,t,digest in json.loads(app.script(TABLE_SNAPSHOT))}
        targets=[key for key,digest in after_tables.items() if before_tables.get(key)!=digest]
        assert targets,'Successful render must durably append its SQLite audit'
        app.stop();app.start()
        # Fault each changed table separately: this includes audit tables even
        # with foreign keys, per-event schemas, or serialized JSON payloads.
        for target in targets:
            app.script(TABLE_FAULT,json.dumps(target),'true')
            try:
                before=state_digest(app);result=c.call('/render','POST',{'profile_id':'testing','kind':'sample_pass','filename':'kept.pdf'},500)
                assert result['error']['code']=='render_failed' and c.call('/documents/kept.pdf',raw=True)[0]==original and state_digest(app)==before,'Failed render write left a new PDF or partial publication'
            finally:app.script(TABLE_FAULT,json.dumps(target),'false')

def main():
    results=[];infra=[];chosen=os.environ.get('DOCUMENT_GATE')
    for i,test in enumerate([check_1,check_2,check_3,check_4,check_5],1):
        if chosen and chosen!=str(i):continue
        try:test();result={'ru_id':f'RU-{i:03d}','passed':True}
        except (AssertionError,CandidateFailure,BrowserTimeout,KeyError,IndexError) as error:
            traceback.print_exc(file=sys.stderr);result={'ru_id':f'RU-{i:03d}','passed':False,'detail':str(error)[-1500:] or type(error).__name__}
        except Exception as error:
            traceback.print_exc(file=sys.stderr);infra.append(f'RU-{i:03d}: {type(error).__name__}: {error}');result={'ru_id':f'RU-{i:03d}','passed':False,'detail':'Unattributed evaluator error'}
        results.append(result)
    print(json.dumps({'harness_ok':not infra,'results':results,'infrastructure_errors':infra}));return 2 if infra else 0

if __name__=='__main__':raise SystemExit(main())
