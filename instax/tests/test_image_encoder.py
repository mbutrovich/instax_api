"""
Instax SP2 Test File.

@jpwsutton 2016/17
"""
import hashlib
import unittest

from instax.instaxImage import InstaxImage


class ImageTests(unittest.TestCase):
    """Instax-SP2 Image Encoding / Decoding Test Class."""

    def test_encode_and_decode_image(self):
        """Test Decoding and then Encoding a premade instax image."""
        encodedImageFile = "instax/tests/testEncodedImage.instax"
        rawInstaxBytes = None
        with open(encodedImageFile, "rb") as infile:
            rawBytes = infile.read()
            rawInstaxBytes = bytearray(rawBytes)
        self.assertEqual(len(rawInstaxBytes), 1440000)

        # Initialize The Instax Image
        instaxImage = InstaxImage()

        # Decode the Image from the Instax Byte Array
        instaxImage.decodeImage(rawInstaxBytes)

        # Re-Encode the image

        encodedImage = instaxImage.encodeImage()
        self.assertEqual(len(encodedImage), 1440000)

        for x in range(1440000):
            if rawInstaxBytes[x] != encodedImage[x]:
                message = f"Mismatch: Index: {x}: {rawInstaxBytes[x]} != {encodedImage[x]}"
                self.fail(message, True)

    def check_pipeline_hash(self, type, expectedLength, expectedHash):
        """Convert and encode the test image, then compare against a known-good hash."""
        instaxImage = InstaxImage(type=type)
        instaxImage.loadImage("instax/tests/test_image.png")
        instaxImage.convertImage()
        encodedImage = bytes(instaxImage.encodeImage())
        self.assertEqual(len(encodedImage), expectedLength)
        self.assertEqual(hashlib.sha256(encodedImage).hexdigest(), expectedHash)

    # The hashes were recorded with Python 3.10 and Pillow 9.3.0. A mismatch means the
    # bytes sent to the printer have changed.
    def test_sp2_pipeline_hash(self):
        """The test image is already 600x800, so this mainly covers rotation and encoding."""
        self.check_pipeline_hash(2, 1440000, "01bfd44395d56374e5e7d420e1df83a46efa1fbee534a5b35384eb25a5c2c246")

    def test_sp3_pipeline_hash(self):
        """The SP-3 image is cropped and resized to 800x800, so this also covers resampling."""
        self.check_pipeline_hash(3, 1920000, "0ce1b722c9f7899647f5eb52e747b116ad611ebc7d31dcab1ccf8c8f36a855f2")


if __name__ == "__main__":

    unittest.main()
