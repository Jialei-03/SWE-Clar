"""Render PDF pages before inspecting staff geometry, independent of PDF object type."""
import pypdfium2
from pypdf import PdfReader
import io,os,re,shutil,subprocess

class OCRUnavailable(RuntimeError):pass

def rendered_labels(image):
    """Recognize visible pitch labels without requiring a PDF text layer."""
    executable=shutil.which(os.environ.get('TESSERACT_BIN','tesseract'))
    if not executable:raise OCRUnavailable('Raster PDF label verification requires benchmark-provided Tesseract with English data')
    data=io.BytesIO();image.save(data,format='PNG')
    # Sparse text handles captions above/below a staff without prescribing layout.
    try:result=subprocess.run([executable,'stdin','stdout','-l','eng','--psm','11'],input=data.getvalue(),capture_output=True,timeout=20)
    except (OSError,subprocess.TimeoutExpired) as error:raise OCRUnavailable('Benchmark OCR launch/timeout failure') from error
    if result.returncode:raise OCRUnavailable('Benchmark OCR could not process the rendered PDF page')
    return result.stdout.decode('utf-8')

def observe(path,expected_labels=()):
    texts=[p.extract_text() or '' for p in PdfReader(path).pages]
    result={'labels':'\n'.join(texts),'staves':[]}
    needs_ocr=not set(expected_labels).issubset(re.findall(r'[A-G](?:#|b)?-?\d+',result['labels'])) if expected_labels else not result['labels'].strip()
    pdf=pypdfium2.PdfDocument(path)
    for index,page in enumerate(pdf):
        im=page.render(scale=2).to_pil().convert('L');w,h=im.size
        if needs_ocr:
            result['labels']+='\n'+rendered_labels(im)
        rows=[]
        for y in range(h):
            xs=[x for x in range(w) if im.getpixel((x,y))<160]
            # A staff line is long relative to this page, but its position is unrestricted.
            if len(xs)>.35*w:rows.append((y,len(xs)))
        groups=[]
        for y,n in rows:
            if groups and y<=groups[-1][-1][0]+1:groups[-1].append((y,n))
            else:groups.append([(y,n)])
        centers=[sum(y*n for y,n in g)/sum(n for y,n in g) for g in groups]
        for i in range(len(centers)-4):
            ys=centers[i:i+5];gaps=[ys[j+1]-ys[j] for j in range(4)];space=sum(gaps)/4
            if space<4 or max(abs(v-space) for v in gaps)>.18*space:continue
            runs=[]
            for y in range(max(0,int(ys[0]-4*space)),min(h,int(ys[-1]+3*space))):
                if any(abs(y-line)<max(2,.13*space) for line in ys):continue
                start=None
                for x in range(w+1):
                    dark=x<w and im.getpixel((x,y))<160
                    if dark and start is None:start=x
                    if not dark and start is not None:
                        length=x-start
                        if .65*space<=length<=1.8*space:runs.append(((start+x-1)/2,y,length))
                        start=None
            clusters=[]
            for x,y,length in sorted(runs,key=lambda r:r[0]):
                group=next((g for g in clusters if abs(x-g[0][0])<.65*space),None)
                if group is None:clusters.append([(x,y,length)])
                else:group.append((x,y,length))
            heads=[]
            for g in clusters:
                # Filled heads occupy several scanlines; stems and isolated ledger lines do not.
                yvalues=sorted(set(t[1] for t in g))
                if len(yvalues)<.25*space or yvalues[-1]-yvalues[0]>1.4*space:continue
                weight=sum(t[2] for t in g)
                x=sum(t[0]*t[2] for t in g)/weight;y=sum(t[1]*t[2] for t in g)/weight
                heads.append({'x':x,'staff_steps':(y-ys[0])/space})
            result['staves'].append({'page':len(result.get('pages',[])),'lines':ys,'spacing':space,'heads':heads})
        result.setdefault('pages',[]).append({'width':w,'height':h})
        page.close()
    pdf.close()
    return result
