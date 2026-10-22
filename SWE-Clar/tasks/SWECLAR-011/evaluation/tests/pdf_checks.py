"""Independent parsing/raster/character evidence for real generated PDFs."""
import ctypes,io,unicodedata
import pypdf,pypdfium2,pypdfium2_raw as raw,zxingcpp
from PIL import Image
from document_support import CandidateFailure

MM=72/25.4
LABELS=[('document_id','Identifiant','المعرّف',3),('name','Nom','الاسم',3),
        ('group','Groupe','المجموعة',3),('contact','Contact','جهة الاتصال',5),
        ('reviewer','Révision','المراجعة',4),('reference','Référence','المرجع',3)]

def compact(value):return ''.join(unicodedata.normalize('NFKC',value).split())

def label_matches(text,expected):
    normalized=compact(text)
    return compact(expected) in normalized or compact(expected) in compact(text[::-1])

def spatial_arabic_label_matches(glyphs,expected):
    """Read Arabic by actual glyph positions, not PDF extraction run order.

    Some engines reorder a diacritic-bearing final letter as a separate run.
    Preserve exact base-letter order and required marks; never use a letter bag.
    """
    from collections import Counter
    ordered=sorted(glyphs,key=lambda g:-(g['box'][0]+g['box'][2])/2)
    actual=unicodedata.normalize('NFKC',''.join(g['character'] for g in ordered))
    expected=unicodedata.normalize('NFKC',expected)
    base=lambda text:''.join(c for c in text if not c.isspace() and not unicodedata.category(c).startswith('M'))
    marks=lambda text:Counter(c for c in text if unicodedata.category(c).startswith('M'))
    return base(actual)==base(expected) and marks(actual)==marks(expected)

def main_ink_components(pixels,width,height,min_height):
    """Count connected letter bodies, excluding detached dots/diacritics."""
    pending={i for i,value in enumerate(pixels) if value<160};bodies=[]
    while pending:
        first=pending.pop();stack=[first];xs=[];ys=[]
        while stack:
            i=stack.pop();x=i%width;y=i//width;xs.append(x);ys.append(y)
            for dx,dy in [(-1,0),(1,0),(0,-1),(0,1),(-1,-1),(-1,1),(1,-1),(1,1)]:
                xx=x+dx;yy=y+dy;j=yy*width+xx
                if 0<=xx<width and 0<=yy<height and j in pending:pending.remove(j);stack.append(j)
        if max(ys)-min(ys)+1>=min_height:bodies.append((min(xs),max(xs),min(ys),max(ys)))
    return bodies

def exclude_diacritic_components(bodies,mark_boxes,tolerance=2):
    """Exclude only whole components contained in actual diacritic glyph boxes."""
    return [body for body in bodies if not any(
        body[0]>=mark[0]-tolerance and body[1]<=mark[1]+tolerance and
        body[2]>=mark[2]-tolerance and body[3]<=mark[3]+tolerance
        for mark in mark_boxes)]

class PDF:
    def __init__(self,data):
        try:self.reader=pypdf.PdfReader(io.BytesIO(data));self.doc=pypdfium2.PdfDocument(data)
        except Exception as e:raise CandidateFailure('Downloaded bytes were not a readable PDF: '+str(e)) from e
        assert len(self.reader.pages)==len(self.doc)==2,'Expected two actual PDF pages'
        for page in self.reader.pages:
            assert abs(float(page.mediabox.width)-210*MM)<0.05 and abs(float(page.mediabox.height)-148*MM)<0.05,'Wrong landscape A5 dimensions'
        self.texts=[page.extract_text() for page in self.reader.pages]
        self.pdfium_texts=[]
        for i in range(2):
            page=self.doc[i];tp=page.get_textpage();self.pdfium_texts.append(tp.get_text_bounded());tp.close();page.close()
        assert all('SAMPLE / NOT VALID' in text for text in self.texts),'Sample marker missing'

    def close(self):self.doc.close()
    def raster(self,side,scale=3):
        page=self.doc[side];bitmap=page.render(scale=scale);im=bitmap.to_pil().convert('RGB');bitmap.close();page.close();return im
    def content(self,values,hidden=()):
        for i,(key,value) in enumerate(values.items()):
            side=0 if key in ['document_id','name','group'] else 1
            if key in hidden:assert all(compact(value) not in compact(''.join(texts)) for texts in [self.texts,self.pdfium_texts]),f'Hidden {key} survived in PDF text'
            else:assert any(compact(value) in compact(texts[side]) for texts in [self.texts,self.pdfium_texts]),f'{key} value omitted, clipped or changed'
        for side in range(2):
            fonts=self.reader.pages[side]['/Resources'].get('/Font',{})
            embedded=False
            for ref in fonts.values():
                font=ref.get_object();descendants=font.get('/DescendantFonts',[font])
                for descendant in descendants:
                    descriptor=descendant.get_object().get('/FontDescriptor')
                    if descriptor:
                        descriptor=descriptor.get_object()
                        name=str(descriptor.get('/FontName',font.get('/BaseFont',''))).lower().replace('-','')
                        if 'dejavusans' in name and any(k in descriptor for k in ['/FontFile','/FontFile2','/FontFile3']):embedded=True
            assert embedded,'Required multilingual text font was not embedded'
        self.labels(hidden)

    def labels(self,hidden=()):
        for index,(key,french,arabic,joins) in enumerate(LABELS):
            side,row=divmod(index,3);y=25+row*29
            page=self.doc[side];text=page.get_textpage()
            left=text.get_text_bounded(10*MM,(148-y-5)*MM,105*MM,(148-y)*MM)
            right=text.get_text_bounded(105*MM,(148-y-5)*MM,200*MM,(148-y)*MM)
            text.close();page.close()
            if key in hidden:
                assert not label_matches(left,french) and not label_matches(right,arabic), 'Hidden field label remains'
                continue
            glyphs=[g for g in self.glyphs(side) if (148-y-5)*MM<=sum(g['box'][j] for j in [1,3])/2<=(148-y)*MM]
            assert glyphs and all('dejavusans' in g['font'].lower().replace('-','') for g in glyphs), 'Labels must actually use DejaVu Sans'
            arabic_glyphs=[g for g in glyphs if g['box'][0]>=105*MM]
            assert label_matches(left,french) and (label_matches(right,arabic) or spatial_arabic_label_matches(arabic_glyphs,arabic)), 'Missing or misplaced bilingual label: '+key
            positions=lambda char:[(g['box'][0]+g['box'][2])/2 for g in arabic_glyphs if char in unicodedata.normalize('NFKC',g['character'])]
            first,last=positions(arabic[0]),positions(arabic[-1])
            assert first and last and max(first)>min(last), 'Arabic label direction must be right to left'
            scale=6;im=self.raster(side,scale)
            # Restrict connected-component counting to actual label glyphs.
            # The optional panel border is valid surrounding decoration, not a
            # broken Arabic letter, and must not enter this text-only crop.
            import math
            crop_box=(math.floor(min(g['box'][0] for g in arabic_glyphs)*scale)-1,
                      math.floor((148*MM-max(g['box'][3] for g in arabic_glyphs))*scale)-1,
                      math.ceil(max(g['box'][2] for g in arabic_glyphs)*scale)+1,
                      math.ceil((148*MM-min(g['box'][1] for g in arabic_glyphs))*scale)+1)
            crop=im.crop(crop_box).convert('L')
            bodies=main_ink_components(list(crop.getdata()),crop.width,crop.height,8*scale*.25)
            # Shadda is taller than a dot and exceeded the generic body-height
            # threshold. Its independently observed glyph box identifies it as
            # a mark; excluding arbitrary small components would hide breaks.
            marks=[]
            for g in arabic_glyphs:
                if all(unicodedata.category(c).startswith('M') for c in unicodedata.normalize('NFKC',g['character'])):
                    x0,y0,x1,y1=g['box']
                    marks.append((x0*scale-crop_box[0],x1*scale-crop_box[0],
                                  (148*MM-y1)*scale-crop_box[1],(148*MM-y0)*scale-crop_box[1]))
            bodies=exclude_diacritic_components(bodies,marks)
            assert 0<len(bodies)<=joins, 'Arabic label must use joined letter bodies: '+key

    def field_text(self,side,row):
        page=self.doc[side];text=page.get_textpage();y=25+row*29
        result=text.get_text_bounded(10*MM,(148-y-29)*MM,200*MM,(148-y-5)*MM);text.close();page.close();return result

    def field_contains(self,side,row,value):
        text=self.field_text(side,row)
        if compact(value) in compact(text):return True
        # PDF readers can reverse word order in a pure RTL span while keeping
        # Arabic glyph order intact. This preserves exact words, not a bag of letters.
        letters=[c for c in value if c.isalpha()]
        if letters and all('ARABIC' in unicodedata.name(c,'') for c in letters):
            return compact(value) in compact(' '.join(reversed(text.split())))
        return False

    def glyphs(self,side):
        page=self.doc[side];tp=page.get_textpage();result=[]
        for i in range(tp.count_chars()):
            cp=raw.FPDFText_GetUnicode(tp.raw,i)
            if not cp or chr(cp).isspace():continue
            color=[ctypes.c_uint() for _ in range(4)]
            okay=raw.FPDFText_GetFillColor(tp.raw,i,*[ctypes.byref(x) for x in color]);assert okay
            box=tp.get_charbox(i)
            flags=ctypes.c_int();length=raw.FPDFText_GetFontInfo(tp.raw,i,None,0,ctypes.byref(flags))
            name=ctypes.create_string_buffer(max(1,length));raw.FPDFText_GetFontInfo(tp.raw,i,name,length,ctypes.byref(flags))
            result.append({'character':chr(cp),'font':name.value.decode(errors='replace'),'size':raw.FPDFText_GetFontSize(tp.raw,i),'weight':raw.FPDFText_GetFontWeight(tp.raw,i),'color':tuple(x.value for x in color),'box':box})
        tp.close();page.close();return result

    def barcode(self,expected):
        found=zxingcpp.read_barcodes(self.raster(1,3))
        assert any(x.format==zxingcpp.BarcodeFormat.PDF417 and x.bytes==expected.encode('utf-8') for x in found),'Back PDF417 did not independently decode to exact reference UTF-8 bytes'


def pixel(image,x_mm,y_mm):
    x=round(x_mm/210*image.width);y=round(y_mm/148*image.height)
    pixels=[image.getpixel((xx,yy)) for xx in range(max(0,x-1),min(image.width,x+2)) for yy in range(max(0,y-1),min(image.height,y+2))]
    return tuple(sorted(p[k] for p in pixels)[len(pixels)//2] for k in range(3))

def near(actual,expected,tolerance=5):return all(abs(a-b)<=tolerance for a,b in zip(actual,expected))

def assert_slot(image,box,size,colors):
    x,y,w,h=box;sw,sh=size;scale=min(w/sw,h/sh);iw,ih=sw*scale,sh*scale;left=x+(w-iw)/2;top=y+(h-ih)/2
    if iw<w-1:assert near(pixel(image,x+0.3,y+h/2),(255,255,255)), 'Image stretched across horizontal letterbox'
    if ih<h-1:assert near(pixel(image,x+w/2,y+0.3),(255,255,255)), 'Image stretched across vertical letterbox'
    for (dx,dy),color in zip([(0.25,0.25),(0.75,0.25),(0.25,0.75),(0.75,0.75)],colors):
        assert near(pixel(image,left+iw*dx,top+ih*dy),color),f'Actual uploaded image pixels missing/misplaced in slot {box}'

def pattern(size=(80,40),colors=((220,30,50),(20,170,70),(35,70,215),(230,190,25))):
    im=Image.new('RGB',size)
    for y in range(size[1]):
        for x in range(size[0]):im.putpixel((x,y),colors[(y>=size[1]/2)*2+(x>=size[0]/2)])
    data=io.BytesIO();im.save(data,format='PNG');return data.getvalue()
