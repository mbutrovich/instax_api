"""The ``instax-print`` command."""

import argparse
import logging
import sys
from pathlib import Path

from PIL import Image

from instax.client import DEFAULT_HOST, DEFAULT_PIN, DEFAULT_PORT, Printer
from instax.errors import InstaxError
from instax.image import prepare_image


def parse_size(value: str) -> tuple[int, int]:
    try:
        width, height = (int(part) for part in value.lower().split("x"))
    except ValueError:
        raise argparse.ArgumentTypeError(f"expected WIDTHxHEIGHT, not {value!r}") from None
    if width <= 0 or height <= 0:
        raise argparse.ArgumentTypeError(f"size must be positive, not {value!r}")
    return width, height


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="instax-print",
        description="Print a photo on a Fujifilm Instax SHARE SP-2 or SP-3. Join the printer's "
        "INSTAX-xxxxxxxx Wi-Fi network first.",
    )
    parser.add_argument("image", nargs="?", help="the image file to print")
    parser.add_argument("--info", action="store_true", help="show printer information instead of printing")
    parser.add_argument(
        "--fit",
        choices=["crop", "contain"],
        default="crop",
        help="crop the image to fill the print, or fit all of it with white bars (default: %(default)s)",
    )
    parser.add_argument("--pin", type=int, default=DEFAULT_PIN, help="the printer's PIN (default: %(default)s)")
    parser.add_argument("--host", default=DEFAULT_HOST, help=argparse.SUPPRESS)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help=argparse.SUPPRESS)
    parser.add_argument("--timeout", type=float, default=15.0, help="network timeout in seconds (default: %(default)s)")
    parser.add_argument(
        "--preview", type=Path, metavar="FILE", help="save the image as it would be printed and exit, without printing"
    )
    parser.add_argument(
        "--size",
        type=parse_size,
        default=(800, 800),
        help="print size for --preview: 800x800 for the SP-3 or 600x800 for the SP-2 (default: 800x800)",
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="log every frame sent and received")
    args = parser.parse_args(argv)
    if args.image is None and not args.info:
        parser.error("an image is required unless --info is given")

    # Configure only this library's logger, so -v does not turn on Pillow's debug output.
    logger = logging.getLogger("instax")
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(message)s"))
        logger.addHandler(handler)
    logger.setLevel(logging.DEBUG if args.verbose else logging.INFO)
    try:
        if args.preview:
            with Image.open(args.image) as image:
                prepare_image(image, *args.size, fit=args.fit).save(args.preview)
            return 0
        printer = Printer(args.host, args.port, pin=args.pin, timeout=args.timeout)
        if args.info:
            info = printer.info()
            print(f"Model: {info.model}")
            print(f"Firmware: {info.firmware}")
            print(f"Hardware: {info.hardware}")
            print(f"Battery: {info.battery}")
            print(f"Film remaining: {info.film_remaining}")
            print(f"Lifetime prints: {info.print_count}")
            print(f"Print size: {info.width}x{info.height}")
            return 0
        printer.print_image(args.image, fit=args.fit)
    except (InstaxError, OSError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    return 0
