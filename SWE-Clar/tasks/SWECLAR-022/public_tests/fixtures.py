"""Independent synthetic receipt pixels prepared before the candidate budget."""
from io import BytesIO
from pathlib import Path
from PIL import Image,ImageDraw


def sample_png(other=False):
    image=Image.new('RGBA',(240,180),'white');draw=ImageDraw.Draw(image)
    draw.rectangle((8,8,231,171),outline='#34574b',width=2)
    draw.text((20,20),'SYNTHETIC RECEIPT',fill='black')
    draw.text((20,50),'Sample B' if other else 'Sample A',fill='black')
    draw.text((20,80),'Item          7.50',fill='black')
    draw.text((20,110),'Training image only',fill='black')
    output=BytesIO();image.save(output,format='PNG');return output.getvalue()


def prepare_samples():
    root=Path('/tmp/sweclar-loyalty-samples');root.mkdir(exist_ok=True)
    for filename,other in [('receipt.png',False),('receipt-other.png',True)]:
        (root/filename).write_bytes(sample_png(other))
    return root
