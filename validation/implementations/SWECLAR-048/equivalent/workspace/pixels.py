"""RGB scaling and PNG output for the preview pipeline."""
import struct
import zlib


def scale(rgb, width, height, output_width, output_height, zoom):
    crop_width, crop_height = width // zoom, height // zoom
    left, top = (width-crop_width)//2, (height-crop_height)//2

    # Keep source positions as byte offsets.  Building each distinct output
    # row once is equivalent to nearest-neighbour sampling while avoiding a
    # temporary list of RGB slices for every output row.
    columns = tuple(3 * (left + x * crop_width // output_width) for x in range(output_width))
    rows = {}
    result = bytearray()
    for y in range(output_height):
        source_y = top + y * crop_height // output_height
        row = rows.get(source_y)
        if row is None:
            source_start = source_y * width * 3
            row = bytearray(output_width * 3)
            for destination, source_offset in enumerate(columns):
                row[destination * 3:destination * 3 + 3] = rgb[
                    source_start + source_offset:source_start + source_offset + 3
                ]
            row = bytes(row)
            rows[source_y] = row
        result.extend(row)
    return bytes(result)


def png(rgb, width, height):
    def chunk(kind, payload):
        return struct.pack('!I',len(payload))+kind+payload+struct.pack('!I',zlib.crc32(kind+payload)&0xffffffff)
    rows=b''.join(b'\x00'+rgb[y*width*3:(y+1)*width*3] for y in range(height))
    return b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('!IIBBBBB',width,height,8,2,0,0,0))+chunk(b'IDAT',zlib.compress(rows))+chunk(b'IEND',b'')
