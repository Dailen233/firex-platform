"""Image validation: magic bytes + actual decode + dimension checks.

Only JPEG and PNG are accepted. Validation trusts decoded content, not the
client-supplied filename or Content-Type.
"""
from __future__ import annotations

import io

from PIL import Image

JPEG_MAGIC = b"\xff\xd8\xff"
PNG_MAGIC = b"\x89PNG\r\n\x1a\n"

SUPPORTED_PIL_FORMATS = {"JPEG", "PNG"}


class UnsupportedImageFormat(Exception):
    pass


class InvalidImage(Exception):
    pass


class ImageDimensionMismatch(Exception):
    pass


def detect_format(data: bytes) -> str:
    if data.startswith(JPEG_MAGIC):
        return "jpeg"
    if data.startswith(PNG_MAGIC):
        return "png"
    raise UnsupportedImageFormat("only JPEG and PNG are supported")


def validate_image(data: bytes, expected_width: int, expected_height: int, max_pixels: int) -> str:
    fmt = detect_format(data)
    try:
        with Image.open(io.BytesIO(data)) as img:
            if img.format not in SUPPORTED_PIL_FORMATS:
                raise UnsupportedImageFormat("only JPEG and PNG are supported")
            w, h = img.size
            if w * h > max_pixels:
                raise InvalidImage(f"image pixel scale {w * h} exceeds limit {max_pixels}")
    except (UnsupportedImageFormat, InvalidImage):
        raise
    except Exception as exc:
        raise InvalidImage("image could not be opened") from exc

    # Full pixel decode. Image.verify() only checks structure and does not load
    # pixels, so a truncated JPEG can pass verify() yet fail on load(). Force the
    # actual decode so truncated/corrupt images are rejected (do not enable
    # Pillow's permissive truncated-image handling).
    try:
        with Image.open(io.BytesIO(data)) as img:
            img.load()
    except Exception as exc:
        raise InvalidImage("image could not be decoded") from exc

    if (w, h) != (expected_width, expected_height):
        raise ImageDimensionMismatch(f"decoded {w}x{h} does not match metadata {expected_width}x{expected_height}")
    return fmt
