"""RGB scaling and PNG output for the preview pipeline."""
import struct
import zlib


def scale(rgb, width, height, output_width, output_height, zoom):
    crop_width, crop_height = width // zoom, height // zoom
    left, top = (width-crop_width)//2, (height-crop_height)//2
    columns = [left + x*crop_width//output_width for x in range(output_width)]
    cache = {}
    result = []
    for y in range(output_height):
        source_y = top + y*crop_height//output_height
        if source_y not in cache:
            start = source_y*width*3
            cache[source_y] = b''.join(rgb[start+x*3:start+x*3+3] for x in columns)
        result.append(cache[source_y])
    return b''.join(result)


def png(rgb, width, height):
    def chunk(kind, payload):
        return struct.pack('!I',len(payload))+kind+payload+struct.pack('!I',zlib.crc32(kind+payload)&0xffffffff)
    rows=b''.join(b'\x00'+rgb[y*width*3:(y+1)*width*3] for y in range(height))
    return b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('!IIBBBBB',width,height,8,2,0,0,0))+chunk(b'IDAT',zlib.compress(rows))+chunk(b'IEND',b'')
