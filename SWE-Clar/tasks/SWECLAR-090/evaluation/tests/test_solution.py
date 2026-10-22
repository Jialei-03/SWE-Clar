from copy import deepcopy
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread
from pathlib import Path
import re
import html
import io,os,subprocess,sys
from pypdf import PdfReader
import pypdfium2 as pdfium
from conftest import load_solution

def params(**extra):
    return dict(title='Example reading collection',start_date='2030-04-01',end_date='2030-04-30',**extra)

def article(ident='article-one',date='2030-04-01',title='Garden & light',body='A fictional garden opened for shared planting.',publication='Example Journal',summary=None):
    return f'<article class="archive-entry" data-id="{html.escape(ident)}" data-date="{date}" data-publication="{publication}"><h2>{html.escape(title)}</h2><div data-field="body">{body}</div>'+('' if summary is None else f'<div data-field="summary">{html.escape(summary)}</div>')+'</article>'

def call(m,tmp,body,cfg=None):
    cfg=cfg or params();saved=deepcopy(cfg);seen=[]
    def fetch(url):seen.append(url);return '<html><body>'+body+'</body></html>'
    result=m.build_article_package(cfg,'https://archive.example.test/collection',str(tmp),fetch_text=fetch)
    assert cfg==saved
    assert seen==['https://archive.example.test/collection'] or ('error' in result and seen==[])
    return result

def artifact_bytes(path):
    # Read submitted artifacts as the submitting UID, without granting the
    # candidate access to the evaluator or requiring insecure file modes.
    p=subprocess.run([sys.executable,'-I','-c','import pathlib,sys;sys.stdout.buffer.write(pathlib.Path(sys.argv[1]).read_bytes())',str(path)],user=1000,group=1000,extra_groups=[],env={'PATH':os.environ['PATH'],'HOME':'/tmp'},capture_output=True,timeout=10)
    assert p.returncode==0,p.stderr.decode(errors='replace')
    return p.stdout

def pdf(tmp,result):
    path=Path(tmp)/result['filename']
    content=artifact_bytes(path)
    assert path.is_file() and content.startswith(b'%PDF-')
    assert Path(result['filename']).name==result['filename']
    reader=PdfReader(io.BytesIO(content))
    assert not reader.is_encrypted and len(reader.pages)>0
    return reader

def normalized(text):return re.sub(r'\s+',' ',text).strip()

def article_id(row):return row.get('article_id',row.get('id'))

def page_number_spans(text,number,total):
    # Recognize conventional visible labels without prescribing serialization.
    # Anchoring to a complete line prevents article prose containing a number
    # from satisfying the page-number requirement or escaping margin checks.
    pattern=rf'(?im)^[ \t]*(?:[-–—][ \t]*)?(?:(?:page|p\.)[ \t]*)?{number}(?:[ \t]*(?:/|of)[ \t]*{total})?(?:[ \t]*[-–—])?[ \t]*\r?$'
    return [match.span() for match in re.finditer(pattern,text)]

@contextmanager
def server(body):
    seen=[]
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            seen.append(self.path);self.send_response(200);self.end_headers();self.wfile.write(body.encode())
        def log_message(self,*args):pass
    service=ThreadingHTTPServer(('127.0.0.1',0),Handler);thread=Thread(target=service.serve_forever,daemon=True);thread.start()
    try:yield f'http://127.0.0.1:{service.server_port}/archive',seen
    finally:service.shutdown();service.server_close();thread.join()

def test_ru_001_real_http_pdf(tmp_path):
    m=load_solution();cfg=params();before=deepcopy(cfg)
    with server(article()) as (url,hits):
        result=m.build_article_package(cfg,url,str(tmp_path))
        assert hits==['/archive'] and cfg==before
    reader=pdf(tmp_path,result)
    assert 'A fictional garden opened for shared planting.' in normalized(reader.pages[1].extract_text())
    def broken(url):raise OSError('Synthetic failure')
    failed=m.build_article_package(cfg,'https://archive.example.test/failure',str(tmp_path/'failure'),fetch_text=broken)
    assert isinstance(failed['error']['code'],str) and failed['error']['code']
    assert not list((tmp_path/'failure').glob('*.pdf'))

def test_ru_002_selection_and_invalid_ranges(tmp_path):
    m=load_solution()
    body=article('first',title='Gardens begin')+article('last',date='2030-04-30',title='GARDENS close')+article('before',date='2030-03-31')+article('after',date='2030-05-01')+article('other',publication='Another Journal')+article('different',title='Unrelated',body='A fictional boat sailed.')
    result=call(m,tmp_path/'valid',body,params(publication='example journal',query='garden'))
    assert [article_id(r) for r in result['articles']]==['first','last']
    text=' '.join(p.extract_text() for p in pdf(tmp_path/'valid',result).pages)
    assert 'Gardens begin' in text and 'GARDENS close' in text and 'Unrelated' not in text
    for i,cfg in enumerate([dict(title='',start_date='2030-04-01',end_date='2030-04-30'),dict(title='Bad',start_date='invalid',end_date='2030-04-30'),dict(title='Bad',start_date='2030-05-01',end_date='2030-04-30')]):
        root=tmp_path/str(i);result=call(m,root,body,cfg)
        assert isinstance(result['error']['code'],str) and bool(result['error']['code']) and not list(root.glob('*.pdf'))

def test_ru_003_parse_order_duplicate_and_text(tmp_path):
    m=load_solution();body=article('z',date='2030-04-02')+article('b',title='  Folded   title ',body='<p>First <em>nested</em> &amp; second.</p><script>SECRET_SCRIPT_TEXT</script><style>HIDDEN_STYLE_TEXT</style><p>Last sentence.</p>')+article('a',title='First by ID')
    result=call(m,tmp_path/'valid',body)
    assert [article_id(r) for r in result['articles']]==['a','b','z']
    row=result['articles'][1]
    assert row['title']=='Folded title' and row['body']=='First nested & second. Last sentence.'
    text=normalized(' '.join(p.extract_text() for p in pdf(tmp_path/'valid',result).pages))
    assert row['body'] in text and 'SECRET_SCRIPT_TEXT' not in text and 'HIDDEN_STYLE_TEXT' not in text
    for i,invalid in enumerate([article('same')+article('same'),article(''),article(date='invalid')]):
        root=tmp_path/str(i);bad=call(m,root,invalid)
        assert bad['error']['code']=='invalid_archive' and not list(root.glob('*.pdf'))

def test_ru_004_supplied_summaries_only(tmp_path):
    m=load_solution();body=article('a',summary='  Supplied concise summary. ')+article('b',summary=' ')
    result=call(m,tmp_path/'with',body,params(include_summaries=True))
    assert result['articles'][0]['summary']=='Supplied concise summary.'
    assert result['articles'][0].get('summary_missing',False) is False
    assert result['articles'][1].get('summary') is None and result['articles'][1]['summary_missing'] is True
    text=' '.join(p.extract_text() for p in pdf(tmp_path/'with',result).pages)
    assert 'Supplied concise summary.' in text
    result=call(m,tmp_path/'without',body)
    assert all('summary' not in r for r in result['articles'])
    assert 'Supplied concise summary.' not in ' '.join(p.extract_text() for p in pdf(tmp_path/'without',result).pages)

def test_ru_005_real_layout_pagination_and_reproducibility(tmp_path):
    m=load_solution()
    long_body=' '.join(f'Sentence {i} describes fictional plants and their seasonal growth.' for i in range(160))
    body=article('long',title='A long synthetic article',body=long_body)+article('short',title='A separate article')
    result=call(m,tmp_path/'one',body);reader=pdf(tmp_path/'one',result)
    assert len(reader.pages)>=3
    assert 'Example reading collection' in reader.pages[0].extract_text()
    assert 'A long synthetic article' in reader.pages[1].extract_text()
    assert 'A separate article' in reader.pages[-1].extract_text()
    body_parts=[]
    for number,page in enumerate(reader.pages[1:-1],2):
        text=page.extract_text()
        # Strip each page's actual standalone label before joining: a footer
        # may otherwise split a sentence continued on the following page.
        for start,end in reversed(page_number_spans(text,number,len(reader.pages))):
            text=text[:start]+text[end:]
        body_parts.append(text)
    body_text=' '.join(body_parts)
    # Check every numbered sentence, including the final content across page boundaries.
    compact=normalized(body_text)
    for i in range(160):assert f'Sentence {i} describes fictional plants' in compact, f'Missing sentence {i}: {compact}'
    assert 'Sentence 159' in compact
    for i,page in enumerate(reader.pages,1):
        assert abs(float(page.mediabox.width)-595.2756)<.1 and abs(float(page.mediabox.height)-841.8898)<.1
        assert page_number_spans(page.extract_text(),i,len(reader.pages)),'Missing sequential visible page number'
    document=pdfium.PdfDocument(artifact_bytes(tmp_path/'one'/result['filename']))
    try:
        for number in range(len(document)):
            page=document[number];textpage=page.get_textpage();width,height=page.get_size()
            spans=page_number_spans(textpage.get_text_range(),number+1,len(document))
            assert spans
            for index in range(textpage.count_chars()):
                char=textpage.get_text_range(index,1)
                if not char.strip():continue
                left,bottom,right,top=textpage.get_charbox(index)
                assert 55<=left<=right<=width-55
                is_number=any(start<=index<end for start,end in spans)
                if is_number:assert 0<=bottom<=top<=height
                else:assert bottom>=55 and top<=height-55
            # Render the actual document, independently of PDF text operators.
            bitmap=page.render(scale=1);image=bitmap.to_pil();assert image.width>590 and image.height>840
            gray=image.convert('L');assert gray.getextrema()[0]<100
            if number in [0,1,len(document)-1]:image.save(tmp_path/f'page-{number+1}.png')
            textpage.close();page.close()
    finally:document.close()
    repeat=call(m,tmp_path/'two',body)
    assert repeat['title']==result['title'] and repeat['filename']==result['filename']
    assert artifact_bytes(tmp_path/'one'/result['filename'])==artifact_bytes(tmp_path/'two'/repeat['filename'])
    empty=call(m,tmp_path/'empty','')
    assert len(pdf(tmp_path/'empty',empty).pages)==1 and empty['articles']==[]
