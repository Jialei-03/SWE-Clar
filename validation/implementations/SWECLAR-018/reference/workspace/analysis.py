"""Validate capture replays, derive pixel measurements, and evaluate quality."""
import math

from vision import measure, parse_pgm


INTEGER_FIELDS = {
    "phase_ms": (100, 10000),
    "threshold": (0, 255),
    "min_area": (1, 16384),
    "max_area": (1, 16384),
    "max_gap_ms": (1, 20000),
}
FLOAT_FIELDS = {
    "max_motion_px": (0, 256),
    "max_lighting_delta": (0, 255),
    "max_area_change": (0, 100),
    "max_gaze_px": (0, 256),
}
CAPABILITY_FIELDS = {
    "fps": (1, 240),
    "width": (1, 128),
    "height": (1, 128),
}


def number(value, low, high, integer=False):
    """Return whether a JSON number has the required kind and bounds."""
    if integer:
        if type(value) is not int:
            return False
    elif type(value) not in (int, float):
        # ``bool`` is deliberately excluded even though it subclasses int.
        return False

    try:
        if not low <= value <= high:
            return False
        return integer or math.isfinite(value)
    except (OverflowError, TypeError):
        return False


def validate(document):
    """Validate the non-image portion of a capture and return its parts.

    This function intentionally checks only frame headers.  In particular, it
    does not parse a frame's PGM string; that lets the capability gate return
    its specified result without decoding image contents.
    """
    if not isinstance(document, dict):
        raise ValueError("Expected a capture object")

    caps = document.get("capabilities")
    config = document.get("config")
    frames = document.get("frames")
    if (not isinstance(caps, dict) or not isinstance(config, dict)
            or not isinstance(frames, list)):
        raise ValueError("Missing capabilities, config or frames")

    for key, bounds in CAPABILITY_FIELDS.items():
        if not number(caps.get(key), *bounds, integer=True):
            raise ValueError("Invalid capability: " + key)

    for key, bounds in INTEGER_FIELDS.items():
        if not number(config.get(key), *bounds, integer=True):
            raise ValueError("Invalid integer config: " + key)
    for key, bounds in FLOAT_FIELDS.items():
        if not number(config.get(key), *bounds):
            raise ValueError("Invalid numeric config: " + key)

    if config["min_area"] > config["max_area"]:
        raise ValueError("Invalid area bounds or frame count")
    if not 1 <= len(frames) <= 100:
        raise ValueError("Invalid area bounds or frame count")

    last_time = -1
    time_limit = 2 * config["phase_ms"]
    for frame in frames:
        if not isinstance(frame, dict):
            raise ValueError("Frames need increasing times, PGM and an in-image target [x,y]")

        timestamp = frame.get("t_ms")
        target = frame.get("target")
        pgm = frame.get("pgm")
        if not number(timestamp, 0, time_limit - 1, integer=True):
            raise ValueError("Invalid frame time")
        if (timestamp <= last_time or not isinstance(pgm, str)
                or len(pgm) > 150000
                or not isinstance(target, list) or len(target) != 2
                or not number(target[0], 0, caps["width"] - 1)
                or not number(target[1], 0, caps["height"] - 1)):
            raise ValueError("Frames need increasing times, PGM and an in-image target [x,y]")
        last_time = timestamp

    return caps, config, frames


def _quality_failure(rows, images, config):
    """Check all replay-derived quality conditions."""
    phase_ms = config["phase_ms"]
    light_count = sum(row["phase"] == "light" for row in rows)
    gaze_count = sum(row["phase"] == "gaze" for row in rows)
    if light_count < 2 or gaze_count < 2:
        return True

    # A null row means target extraction failed.  Keep it in the returned
    # series, but do not permit it to influence motion or threshold decisions.
    if any(row["area"] is None for row in rows):
        return True

    max_gap = config["max_gap_ms"]
    if rows[0]["t_ms"] > max_gap:
        return True
    for previous, current in zip(rows, rows[1:]):
        if current["t_ms"] - previous["t_ms"] > max_gap:
            return True
    if 2 * phase_ms - rows[-1]["t_ms"] > max_gap:
        return True

    max_motion = config["max_motion_px"]
    max_lighting_delta = config["max_lighting_delta"]
    means = [sum(image["pixels"]) / len(image["pixels"]) for image in images]
    for previous, current, previous_mean, current_mean in zip(
            rows, rows[1:], means, means[1:]):
        motion = math.hypot(current["cx"] - previous["cx"],
                            current["cy"] - previous["cy"])
        if motion > max_motion:
            return True
        if abs(current_mean - previous_mean) > max_lighting_delta:
            return True
    return False


def classify(rows, images, config):
    """Apply quality gates before the deterministic optical decision."""
    if _quality_failure(rows, images, config):
        return "not_measurable", "quality"

    light_areas = [row["area"] for row in rows if row["phase"] == "light"]
    gaze_errors = [row["gaze_error"] for row in rows if row["phase"] == "gaze"]
    minimum_area = min(light_areas)
    relative_area_change = (max(light_areas) - minimum_area) / minimum_area
    maximum_gaze_error = max(gaze_errors)

    if (relative_area_change > config["max_area_change"]
            or maximum_gaze_error > config["max_gaze_px"]):
        return "deviation", "threshold"
    return "stable", "within_limits"


def analyze(document):
    """Validate and process a complete capture replay."""
    caps, config, frames = validate(document)

    # This gate deliberately precedes all calls to parse_pgm.  Malformed image
    # contents therefore cannot turn a capability failure into a parse error.
    if caps["fps"] < 10 or caps["width"] < 16 or caps["height"] < 16:
        return {"verdict": "not_measurable", "reason": "capability", "measurements": []}

    images = []
    for frame in frames:
        image = parse_pgm(frame["pgm"])
        if (image["width"], image["height"]) != (caps["width"], caps["height"]):
            raise ValueError("Frame dimensions do not match capabilities")
        images.append(image)

    rows = []
    for frame, image in zip(frames, images):
        result = measure(image, config)
        row = {
            "t_ms": frame["t_ms"],
            "phase": "light" if frame["t_ms"] < config["phase_ms"] else "gaze",
            "area": None,
            "cx": None,
            "cy": None,
            "gaze_error": None,
        }
        if result is not None:
            row.update(result)
            row["gaze_error"] = math.hypot(
                result["cx"] - frame["target"][0],
                result["cy"] - frame["target"][1],
            )
        rows.append(row)

    verdict, reason = classify(rows, images, config)
    return {"verdict": verdict, "reason": reason, "measurements": rows}
