"""Small PNG framebuffer control using only the prepared standard library.

This rejects spatially uniform clears. It does not establish perspective or
correct clue geometry, which remain beyond this deliberately narrow oracle.
"""
import base64
import struct
import zlib
from collections import Counter

def png_pixels(encoded):
 raw=base64.b64decode(encoded);assert raw[:8]==b'\x89PNG\r\n\x1a\n'
 offset=8;compressed=[];width=height=channels=None
 while offset<len(raw):
  size=struct.unpack('!I',raw[offset:offset+4])[0];kind=raw[offset+4:offset+8];data=raw[offset+8:offset+8+size];offset+=12+size
  if kind==b'IHDR':
   width,height,depth,color,compression,filtering,interlace=struct.unpack('!2I5B',data)
   # Chromium screenshots are 8-bit RGB/RGBA noninterlaced PNG.
   assert depth==8 and color in (2,6) and interlace==0 and compression==filtering==0
   channels=3 if color==2 else 4
  elif kind==b'IDAT':compressed.append(data)
  elif kind==b'IEND':break
 assert width and height and channels
 decoded=zlib.decompress(b''.join(compressed));stride=width*channels;assert len(decoded)==height*(stride+1)
 prior=bytearray(stride);rows=[]
 def paeth(a,b,c):
  p=a+b-c;distances=[abs(p-a),abs(p-b),abs(p-c)];return (a,b,c)[distances.index(min(distances))]
 for y in range(height):
  start=y*(stride+1);kind=decoded[start];row=bytearray(decoded[start+1:start+1+stride]);assert kind in range(5)
  for x in range(stride):
   left=row[x-channels] if x>=channels else 0;up=prior[x];corner=prior[x-channels] if x>=channels else 0
   predictor=(0,left,up,(left+up)//2,paeth(left,up,corner))[kind];row[x]=(row[x]+predictor)&255
  rows.append([tuple(row[x:x+3]) for x in range(0,stride,channels)]);prior=row
 return rows

def scene_content(encoded):
 rows=png_pixels(encoded);height=len(rows);width=len(rows[0]);assert width>4 and height>4
 # Ignore the outermost pixels so a CSS edge cannot make a clear look like a scene.
 interior=[row[1:-1] for row in rows[1:-1]];colors=Counter(pixel for row in interior for pixel in row)
 background=colors.most_common(1)[0][0]
 occupied=[(x,y) for y,row in enumerate(interior) for x,pixel in enumerate(row) if pixel!=background]
 # Spatial content must occupy multiple rows AND columns, not one stray pixel.
 assert len({x for x,y in occupied})>1 and len({y for x,y in occupied})>1,'Uniform/empty interior framebuffer'
 return {'width':width,'height':height,'colors':len(colors),'non_background_pixels':len(occupied)}
