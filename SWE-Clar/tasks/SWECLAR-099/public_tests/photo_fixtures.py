"""Synthetic service accounts and JPEG color cards; no private assertions."""
from PIL import Image,ImageDraw
import io

def configuration():
 return {'countdown':3,'response_window':60,'users':[{'id':'user-'+c,'password':'synthetic-passphrase','phones':['+1202555010'+str(i)]} for i,c in enumerate('abcde')],'rooms':[{'id':'room-one','title':'Synthetic group','members':['user-a','user-b','user-c','user-d']},{'id':'room-two','title':'Synthetic pair','members':['user-d','user-e']}]}

def jpeg(variant=0):
 colors=[(220,35,20),(20,190,55),(225,170,15)];image=Image.new('RGB',(96,80),colors[variant%3]);draw=ImageDraw.Draw(image);draw.rectangle((64,0,95,79),fill=(15,35,220));exif=Image.Exif();exif[315]='Synthetic fixture attribution';exif[270]='Independent color card; no person';stream=io.BytesIO();image.save(stream,format='JPEG',quality=95,exif=exif);return stream.getvalue()
