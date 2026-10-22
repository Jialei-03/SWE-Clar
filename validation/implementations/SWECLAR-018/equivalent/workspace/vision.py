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


_FOUR_NEIGHBOURS = ((-1, 0), (1, 0), (0, -1), (0, 1))


def _dark_components(image, threshold):
    """Yield aggregate data for each four-connected dark component.

    Walking a component through coordinate offsets keeps the connectivity
    rule in one place.  Only aggregate values are retained, so the traversal
    does not depend on a component's visit order when calculating its center.
    """
    width = image["width"]
    height = image["height"]
    pixels = image["pixels"]
    visited = bytearray(width * height)

    for origin, sample in enumerate(pixels):
        if visited[origin] or sample > threshold:
            continue

        visited[origin] = 1
        pending = [origin]
        count = 0
        sum_x = 0
        sum_y = 0
        touches_border = False

        while pending:
            index = pending.pop()
            y, x = divmod(index, width)
            count += 1
            sum_x += x
            sum_y += y
            touches_border = touches_border or (
                x == 0 or x == width - 1 or y == 0 or y == height - 1
            )

            for offset_x, offset_y in _FOUR_NEIGHBOURS:
                neighbour_x = x + offset_x
                neighbour_y = y + offset_y
                if not (0 <= neighbour_x < width and 0 <= neighbour_y < height):
                    continue
                neighbour = neighbour_y * width + neighbour_x
                if (not visited[neighbour]
                        and pixels[neighbour] <= threshold):
                    visited[neighbour] = 1
                    pending.append(neighbour)

        yield count, sum_x, sum_y, touches_border


def measure(image, config):
    """Return the uniquely largest valid dark four-connected component.

    A component is a candidate only when its thresholded pixels form the
    unique largest component, fit the configured area interval, and do not
    touch the image border.  Returning ``None`` represents an unavailable
    measurement while leaving the caller free to retain the frame row.
    """
    largest_count = 0
    largest = None
    largest_component_count = 0

    for component in _dark_components(image, config["threshold"]):
        count = component[0]
        if count > largest_count:
            largest_count = count
            largest = component
            largest_component_count = 1
        elif count == largest_count:
            largest_component_count += 1

    if largest is None or largest_component_count != 1:
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
