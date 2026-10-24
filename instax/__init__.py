"""Print photos on Fujifilm Instax SHARE SP-2 and SP-3 printers over Wi-Fi."""

from importlib.metadata import version

from instax.client import Printer, PrinterInfo
from instax.errors import (
    InstaxError,
    PrinterError,
    PrintTimeoutError,
    ProtocolError,
    UnsupportedPrinterError,
)
from instax.image import decode_image, encode_image, prepare_image

__version__ = version("instax-api")

__all__ = [
    "InstaxError",
    "PrintTimeoutError",
    "Printer",
    "PrinterError",
    "PrinterInfo",
    "ProtocolError",
    "UnsupportedPrinterError",
    "decode_image",
    "encode_image",
    "prepare_image",
]
