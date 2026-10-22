"""Independent MIDI, PDF renderer and JS compiler capability check."""
import io,json,subprocess,re
from PIL import Image,ImageDraw,ImageFont
import mido,pypdfium2
from pypdf import PdfWriter
w=PdfWriter();w.add_blank_page(width=120,height=120);b=io.BytesIO();w.write(b)
d=pypdfium2.PdfDocument(b.getvalue());assert d[0].render().to_pil().size==(120,120)
m=mido.MidiFile();t=mido.MidiTrack();m.tracks.append(t);t.append(mido.Message('note_on',note=60));b=io.BytesIO();m.save(file=b)
assert mido.MidiFile(file=io.BytesIO(b.getvalue())).tracks[0][0].note==60
subprocess.run(['node','-e',"const r=require; r(process.env.NOTATION_NODE_MODULES+'/@tonejs/midi');r(process.env.NOTATION_NODE_MODULES+'/pdf-lib');r(process.env.NOTATION_NODE_MODULES+'/esbuild').transformSync('let a=1');"],check=True)
image=Image.new('RGB',(800,100),'white')
# A monospaced fixture avoids ambiguous glyph spacing without weakening OCR assertions.
font=ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf',40)
ImageDraw.Draw(image).text((20,20),'C4 E4 G4 C5',font=font,fill='black')
buffer=io.BytesIO();image.save(buffer,format='PNG')
ocr=subprocess.run(['tesseract','stdin','stdout','-l','eng','--psm','7'],input=buffer.getvalue(),capture_output=True,timeout=20,check=True)
assert {'C4','E4','G4','C5'} <= set(re.findall(r'[A-G](?:#|b)?-?\d+',ocr.stdout.decode())),ocr.stdout
print(json.dumps({'passed':True,'checks':['MIDI roundtrip','PDF rendering','Node MIDI/PDF packages','Linux esbuild','Rendered pitch OCR with English data']}))
