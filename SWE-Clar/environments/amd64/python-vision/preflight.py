"""Independent OCR, image processing and base web environment health."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from PIL import Image, ImageDraw, ImageFont, __version__ as pillow_version


def main():
    base = subprocess.run([sys.executable, '-I', '/opt/sweclar/web_preflight.py'],capture_output=True,text=True,check=True)
    web = json.loads(base.stdout)
    assert web['passed']
    font_path = Path('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf')
    assert font_path.is_file()
    with tempfile.TemporaryDirectory(prefix='vision-health-') as directory:
        image = Image.new('RGB', (1000, 200), 'white')
        draw = ImageDraw.Draw(image);font = ImageFont.truetype(str(font_path), 36)
        draw.text((24, 24), 'Me: The draft is ready', fill='black', font=font)
        draw.text((24, 92), 'Peer: Please share the draft', fill='black', font=font)
        path = Path(directory) / 'synthetic.png';image.save(path)
        with Image.open(path) as verified:
            assert verified.format == 'PNG' and verified.size == (1000, 200);verified.verify()
        ocr = subprocess.run(['tesseract', str(path), 'stdout', '-l', 'eng', '--psm', '6'],capture_output=True,text=True,check=True,timeout=20)
        lines = [' '.join(line.split()) for line in ocr.stdout.splitlines() if line.strip()]
        assert lines == ['Me: The draft is ready', 'Peer: Please share the draft'], lines
    version = subprocess.run(['tesseract','--version'],capture_output=True,text=True,check=True).stdout.splitlines()[0]
    languages = subprocess.run(['tesseract','--list-langs'],capture_output=True,text=True,check=True).stdout.splitlines()
    assert 'eng' in languages and 'osd' in languages
    print(json.dumps({'passed':True,'base_web':web,'pillow':pillow_version,'tesseract':version,'english_ocr_executed':True,'png_decode_and_verify':True,'font':str(font_path),'candidate_code_loaded':False,'dependencies_installed_during_attempt':False}))


if __name__ == '__main__':main()
