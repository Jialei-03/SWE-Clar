"""Synthetic geometric portraits, not photographs or customer material."""
from pathlib import Path
from PIL import Image,ImageDraw
def write_images(directory):
    directory=Path(directory);directory.mkdir(exist_ok=True)
    image=Image.new('RGB',(128,192),(25,55,75));d=ImageDraw.Draw(image)
    for y in range(192):d.line((0,y,127,y),fill=(25+y//4,55+y//5,75+y//6))
    d.polygon([(59,85),(9,48),(15,125),(58,115)],fill=(195,216,229),outline=(80,110,140));d.polygon([(70,85),(120,48),(115,125),(70,115)],fill=(195,216,229),outline=(80,110,140))
    d.ellipse((44,28,84,77),fill=(206,157,121),outline=(90,60,40),width=2);d.arc((43,24,85,62),180,360,fill=(55,35,30),width=10)
    d.ellipse((53,47,57,51),fill='black');d.ellipse((70,47,74,51),fill='black');d.arc((55,54,74,67),0,180,fill=(120,55,55),width=2)
    d.polygon([(49,77),(79,77),(89,162),(39,162)],fill=(96,60,155),outline=(40,30,65));image.save(directory/'template.png')
    face=Image.new('RGB',(96,96),(218,222,198));d=ImageDraw.Draw(face);d.ellipse((16,8,80,90),fill=(172,114,78),outline=(64,45,28),width=3);d.arc((11,3,85,61),175,365,fill=(30,25,23),width=16)
    d.ellipse((30,39,36,45),fill=(20,30,20));d.ellipse((60,39,66,45),fill=(20,30,20));d.line((48,44,43,59,51,59),fill=(130,75,40),width=2);d.arc((32,59,65,78),0,180,fill=(112,42,32),width=3);face.save(directory/'face.png')
def base_config(inventory):
    return {**inventory,'assets':['template.png','face.png'],'template_asset':'template.png','face_asset':'face.png','prompt':'illustrated portrait, a character with wings','negative_prompt':'blur, artifacts','models':{'checkpoint':'v1-5-pruned-emaonly-fp16.safetensors','controlnet':'control-canny-fp16.safetensors','clip_vision':'ViT-H-fp16.safetensors','ipadapter':'ip-adapter-plus-face_sd15.safetensors'},'width':1024,'height':1536,'sample_width':128,'sample_height':192,'face_crop':{'x':16,'y':8,'width':64,'height':80},'edit_box':{'x':352,'y':224,'width':320,'height':392},'seed':17,'steps':1,'vram_gb':0}
