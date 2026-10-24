"""Preparing photos for the printer and encoding them in its raw image format.

The printer takes uncompressed 8-bit RGB. Rows go from the bottom of the print to the
top, and each row holds all of its red values, then all green, then all blue.
"""

from typing import Literal

from PIL import Image, ImageOps

Fit = Literal["crop", "contain"]
WHITE = (255, 255, 255)


def prepare_image(image: Image.Image, width: int, height: int, fit: Fit = "crop") -> Image.Image:
    """Return an RGB copy of ``image`` sized to exactly ``width`` x ``height``.

    The EXIF orientation is applied and transparent areas become white. With
    ``fit="crop"`` the image is scaled to fill the print and the overflow is cropped
    evenly from both sides. With ``fit="contain"`` the whole image is scaled to fit
    and centered on white.
    """
    if fit not in ("crop", "contain"):
        raise ValueError(f"unknown fit {fit!r}, expected 'crop' or 'contain'")
    image = _flatten(ImageOps.exif_transpose(image))
    if fit == "crop":
        return ImageOps.fit(image, (width, height))
    return ImageOps.pad(image, (width, height), color=WHITE)


def _flatten(image: Image.Image) -> Image.Image:
    """Convert any image mode to RGB, compositing transparency onto white."""
    if image.mode in ("RGBA", "LA", "PA") or "transparency" in image.info:
        rgba = image.convert("RGBA")
        return Image.alpha_composite(Image.new("RGBA", rgba.size, WHITE), rgba).convert("RGB")
    return image.convert("RGB")


def encode_image(image: Image.Image) -> bytes:
    """Encode an RGB image in the printer's raw format.

    >>> image = Image.new("RGB", (2, 2))
    >>> image.putdata([(1, 2, 3), (4, 5, 6), (7, 8, 9), (10, 11, 12)])
    >>> list(encode_image(image))
    [7, 10, 8, 11, 9, 12, 1, 4, 2, 5, 3, 6]
    """
    if image.mode != "RGB":
        raise ValueError(f"image mode must be RGB, not {image.mode}")
    width = image.width
    bands = [band.tobytes() for band in image.transpose(Image.Transpose.FLIP_TOP_BOTTOM).split()]
    return b"".join(band[start : start + width] for start in range(0, len(bands[0]), width) for band in bands)


def decode_image(data: bytes, width: int, height: int) -> Image.Image:
    """Decode the printer's raw format back into an RGB image."""
    if len(data) != width * height * 3:
        raise ValueError(f"expected {width * height * 3} bytes for {width}x{height}, got {len(data)}")
    row_size = width * 3
    bands = [
        Image.frombytes(
            "L",
            (width, height),
            b"".join(data[start + offset : start + offset + width] for start in range(0, len(data), row_size)),
        )
        for offset in (0, width, 2 * width)
    ]
    return Image.merge("RGB", bands).transpose(Image.Transpose.FLIP_TOP_BOTTOM)
