"""Deterministic parsing and pixel operations for grayscale calibration frames."""
import re


_ASCII_WHITESPACE = frozenset(" \t\n\r\v\f")
_UNSIGNED_INTEGER = re.compile(r"[0-9]+\Z")


def _pgm_tokens(text):
    """Tokenize an ASCII P2 document, removing line comments."""
    if not isinstance(text, str) or len(text) > 150000:
        raise ValueError("Expected a bounded P2 PGM string")
    # P2 is an ASCII format.  In particular, do not let Python's broader
    # Unicode whitespace rules silently turn a non-ASCII document into a PGM.
    if not text.isascii():
        raise ValueError("PGM must contain ASCII text")

    tokens = []
    index = 0
    length = len(text)
    while index < length:
        character = text[index]
        if character in _ASCII_WHITESPACE:
            index += 1
            continue
        if character == "#":
            # A comment ends at either of the two common ASCII line endings.
            index += 1
            while index < length and text[index] not in "\r\n":
                index += 1
            continue

        start = index
        while (index < length and text[index] not in _ASCII_WHITESPACE
               and text[index] != "#"):
            index += 1
        tokens.append(text[start:index])
    return tokens


def _unsigned_integer(token):
    return bool(_UNSIGNED_INTEGER.fullmatch(token))


def parse_pgm(text):
    """Parse a bounded, plain ASCII P2 PGM into row-major pixel samples."""
    words = _pgm_tokens(text)
    if len(words) < 4 or words[0] != "P2":
        raise ValueError("Expected P2 width height 255 followed by pixels")
    if any(not _unsigned_integer(word) for word in words[1:]):
        raise ValueError("PGM samples must be unsigned integers")

    width, height, maximum = map(int, words[1:4])
    if not (1 <= width <= 128 and 1 <= height <= 128 and maximum == 255):
        raise ValueError("PGM dimensions must be 1..128 and maximum 255")

    pixels = list(map(int, words[4:]))
    if len(pixels) != width * height or any(pixel > 255 for pixel in pixels):
        raise ValueError("Incorrect PGM sample count or value")
    return {"width": width, "height": height, "pixels": pixels}


def measure(image, config):
    """Return the uniquely largest valid dark four-connected component.

    A component is a candidate only when its thresholded pixels form the
    unique largest component, fit the configured area interval, and do not
    touch the image border.  Returning ``None`` represents an unavailable
    measurement while leaving the caller free to retain the frame row.
    """
    width = image["width"]
    height = image["height"]
    pixels = image["pixels"]
    threshold = config["threshold"]

    # Use one byte per sample for deterministic, low-overhead visitation.
    visited = bytearray(width * height)
    largest_count = 0
    largest = None
    tied = False

    for start, value in enumerate(pixels):
        if visited[start] or value > threshold:
            continue

        visited[start] = 1
        stack = [start]
        count = 0
        sum_x = 0
        sum_y = 0
        touches_border = False

        while stack:
            index = stack.pop()
            x = index % width
            y = index // width
            count += 1
            sum_x += x
            sum_y += y
            if x == 0 or x == width - 1 or y == 0 or y == height - 1:
                touches_border = True

            if x:
                neighbour = index - 1
                if not visited[neighbour] and pixels[neighbour] <= threshold:
                    visited[neighbour] = 1
                    stack.append(neighbour)
            if x + 1 < width:
                neighbour = index + 1
                if not visited[neighbour] and pixels[neighbour] <= threshold:
                    visited[neighbour] = 1
                    stack.append(neighbour)
            if y:
                neighbour = index - width
                if not visited[neighbour] and pixels[neighbour] <= threshold:
                    visited[neighbour] = 1
                    stack.append(neighbour)
            if y + 1 < height:
                neighbour = index + width
                if not visited[neighbour] and pixels[neighbour] <= threshold:
                    visited[neighbour] = 1
                    stack.append(neighbour)

        if count > largest_count:
            largest_count = count
            largest = (count, sum_x, sum_y, touches_border)
            tied = False
        elif count == largest_count:
            tied = True

    if largest is None or tied:
        return None

    count, sum_x, sum_y, touches_border = largest
    if (touches_border or count < config["min_area"]
            or count > config["max_area"]):
        return None
    return {
        "area": count,
        "cx": sum_x / count,
        "cy": sum_y / count,
    }
