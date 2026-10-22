import tempfile,json
from pathlib import Path
import reportlab,pypdf,pypdfium2
from reportlab.pdfgen import canvas
assert reportlab.Version=='4.4.9'
with tempfile.TemporaryDirectory() as temp:
 path=Path(temp)/'probe.pdf';c=canvas.Canvas(str(path));c.drawString(60,750,'synthetic PDF capability');c.save()
 assert 'synthetic PDF capability' in pypdf.PdfReader(path).pages[0].extract_text()
 doc=pypdfium2.PdfDocument(str(path));page=doc[0];image=page.render().to_pil();assert image.convert('L').getextrema()[0]<100;page.close();doc.close()
print(json.dumps({'ready':True,'actual_pdf_text_and_raster':True}))
