"""Tests for image preparation and encoding."""

import hashlib
import io
from pathlib import Path

import pytest
from PIL import Image

from instax.image import decode_image, encode_image, prepare_image

HERE = Path(__file__).parent
WHITE = (255, 255, 255)
RED = (255, 0, 0)


def test_encode_layout():
    image = Image.new("RGB", (2, 2))
    image.putdata([(1, 2, 3), (4, 5, 6), (7, 8, 9), (10, 11, 12)])
    # Rows go bottom to top. Each row is all red values, then all green, then all blue.
    assert encode_image(image) == bytes([7, 10, 8, 11, 9, 12, 1, 4, 2, 5, 3, 6])


def test_encode_one_pixel():
    assert encode_image(Image.new("RGB", (1, 1), (1, 2, 3))) == bytes([1, 2, 3])


def test_encode_rejects_other_modes():
    with pytest.raises(ValueError, match="RGB"):
        encode_image(Image.new("RGBA", (2, 2)))


def test_decode_then_encode():
    data = (HERE / "sp2_encoded_image.bin").read_bytes()
    assert encode_image(decode_image(data, 600, 800)) == data


def test_decode_wrong_length():
    with pytest.raises(ValueError):
        decode_image(bytes(11), 2, 2)


# The hashes were recorded with Python 3.10 and Pillow 9.3.0. A mismatch means the
# bytes sent to the printer have changed.
@pytest.mark.parametrize(
    "width, height, expected",
    [
        (600, 800, "01bfd44395d56374e5e7d420e1df83a46efa1fbee534a5b35384eb25a5c2c246"),
        (800, 800, "0ce1b722c9f7899647f5eb52e747b116ad611ebc7d31dcab1ccf8c8f36a855f2"),
    ],
)
def test_pipeline_hash(width, height, expected):
    with Image.open(HERE / "test_image.png") as source:
        data = encode_image(prepare_image(source, width, height))
    assert len(data) == width * height * 3
    assert hashlib.sha256(data).hexdigest() == expected


def test_crop_fills_frame():
    prepared = prepare_image(Image.new("RGB", (20, 40), RED), 40, 40)
    assert prepared.size == (40, 40)
    assert prepared.getpixel((0, 20)) == RED


def test_contain_adds_white_bars():
    prepared = prepare_image(Image.new("RGB", (2, 4), RED), 4, 4, fit="contain")
    assert prepared.size == (4, 4)
    assert [prepared.getpixel((x, 2)) for x in range(4)] == [WHITE, RED, RED, WHITE]


def test_transparency_becomes_white():
    prepared = prepare_image(Image.new("RGBA", (2, 2), (0, 0, 0, 0)), 2, 2)
    assert prepared.mode == "RGB"
    assert prepared.getcolors() == [(4, WHITE)]


@pytest.mark.parametrize("mode", ["L", "P", "LA", "CMYK", "I;16"])
def test_other_modes(mode):
    prepared = prepare_image(Image.new(mode, (3, 3)), 2, 2)
    assert prepared.mode == "RGB"
    assert prepared.size == (2, 2)


def test_exif_orientation():
    # Orientation 6 means the stored 4x2 pixels display as a 2x4 portrait image.
    image = Image.new("RGB", (4, 2), RED)
    exif = image.getexif()
    exif[0x0112] = 6
    buffer = io.BytesIO()
    image.save(buffer, "PNG", exif=exif)
    with Image.open(buffer) as stored:
        prepared = prepare_image(stored, 2, 4, fit="contain")
    assert prepared.getcolors() == [(8, RED)]


def test_unknown_fit():
    with pytest.raises(ValueError, match="fit"):
        prepare_image(Image.new("RGB", (2, 2)), 2, 2, fit="stretch")
