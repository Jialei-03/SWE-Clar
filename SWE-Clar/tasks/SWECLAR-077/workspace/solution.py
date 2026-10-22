from copy import deepcopy
from pathlib import Path
import json,math,re,os,tempfile,base64
from document_converter import convert_pdf

def fail(state,code):
    out=deepcopy(state);out.pop('result',None);out['error']={'code':code};return out

def source_path(root,relative):
    base=Path(root).resolve();p=(base/relative).resolve()
    if not p.is_relative_to(base) or not p.is_file():raise ValueError('invalid source')
    return p

def atomic(path,data):
    path.parent.mkdir(parents=True,exist_ok=True);temp=None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent,delete=False) as f:temp=Path(f.name);f.write(data)
        os.replace(temp,path)
    finally:
        if temp:temp.unlink(missing_ok=True)

def process_site_action(state,action,output_root,source_root):
    original=deepcopy(state);out=deepcopy(state);a=deepcopy(action)
    for k in ['assets','pages','pdfs','letterheads','documents']:out.setdefault(k,{})
    out.pop('result',None);out.pop('error',None);kind=a.get('type');root=Path(output_root).resolve()
    valid_id=lambda v:isinstance(v,str) and re.fullmatch(r'[A-Za-z0-9_-]+',v) is not None
    if kind=='upsert_page':
        pid=a.get('page_id');width=a.get('viewport_width');ids=a.get('asset_ids',[]);sections=a.get('sections',[])
        if not valid_id(pid) or not isinstance(width,(int,float)) or isinstance(width,bool) or not math.isfinite(width) or width<=0 or not isinstance(a.get('title'),str) or not isinstance(a.get('body'),str) or not isinstance(ids,list) or not all(isinstance(x,str) and x in out['assets'] for x in ids) or not isinstance(sections,list) or not all(isinstance(x,str) for x in sections):return fail(original,'invalid_page')
        try:
            images=[]
            for ident in ids:
                p=source_path(source_root,out['assets'][ident]['path']);data=p.read_bytes()
                if not data.startswith(b'\x89PNG\r\n\x1a\n'):raise ValueError('invalid PNG')
                images.append({'id':ident,'data':'data:image/png;base64,'+base64.b64encode(data).decode()})
        except Exception:return fail(original,'invalid_page')
        page={'title':a['title'],'body':a['body'],'sections':sections,'asset_ids':ids,'images':images}
        if pid in out['pages'] and 'seo' in out['pages'][pid]:page['seo']=out['pages'][pid]['seo']
        try:atomic(root/(pid+'.json'),json.dumps(page,ensure_ascii=False).encode())
        except Exception:return fail(original,'write_failed')
        out['pages'][pid]=page;out['result']={'page_id':pid,'file':pid+'.json'}
    elif kind=='set_seo':
        pid=a.get('page_id');title=a.get('title');description=a.get('description');path=a.get('canonical_path')
        if not valid_id(pid) or pid not in out['pages'] or not isinstance(title,str) or not title.strip() or not isinstance(description,str) or not description.strip() or not isinstance(path,str) or not path.startswith('/') or path.startswith('//') or any(c in path for c in ['\\','\r','\n']):return fail(original,'invalid_seo')
        seo={'title':title.strip(),'description':description.strip(),'canonical_path':path,'indexable':True};page=deepcopy(out['pages'][pid]);page['seo']=seo
        try:atomic(root/(pid+'.json'),json.dumps(page,ensure_ascii=False).encode())
        except Exception:return fail(original,'write_failed')
        out['pages'][pid]=page;out['result']=seo
    elif kind=='convert_pdf':
        did=a.get('document_id');pdf=out['pdfs'].get(a.get('pdf_id'));head=out['letterheads'].get(a.get('letterhead_id'))
        if not valid_id(did) or did in out['documents'] or (root/(str(did)+'.docx')).exists() or not isinstance(pdf,dict) or pdf.get('type')!='pdf' or not isinstance(head,dict):return fail(original,'invalid_document')
        try:
            source=source_path(source_root,pdf['path']);template=source_path(source_root,head['path'])
            data=convert_pdf(source,template);atomic(root/(did+'.docx'),data)
        except Exception:return fail(original,'invalid_document')
        out['documents'][did]={'file':did+'.docx','letterhead_id':a['letterhead_id'],'editable':True};out['result']=deepcopy(out['documents'][did])
    else:return fail(original,'unknown_action')
    return out
