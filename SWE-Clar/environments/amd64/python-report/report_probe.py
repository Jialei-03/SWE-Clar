import io,json,os
from PIL import Image
import reportlab,pypdf,charset_normalizer
from reportlab.pdfgen import canvas
from reportlab.lib.utils import ImageReader
assert os.getuid()==1000
assert reportlab.Version=='4.4.9' and pypdf.__version__=='6.10.0' and charset_normalizer.__version__=='3.4.7'
im=Image.new('RGB',(12,10),(200,20,30));encoded=io.BytesIO();im.save(encoded,format='JPEG');decoded=Image.open(io.BytesIO(encoded.getvalue()));assert decoded.size==(12,10)
out=io.BytesIO();pdf=canvas.Canvas(out);pdf.drawString(40,700,'report capability');pdf.drawImage(ImageReader(decoded),40,600,width=60,height=50);pdf.save()
document=pypdf.PdfReader(io.BytesIO(out.getvalue()));assert 'report capability' in document.pages[0].extract_text();assert len(document.pages[0].images)==1
assert document.pages[0].images[0].image.size==(12,10)
print(json.dumps({'passed':True,'uid':os.getuid(),'reportlab':reportlab.Version,'pypdf':pypdf.__version__,'charset_normalizer':charset_normalizer.__version__,'actual_jpeg_pdf_roundtrip':True}))
