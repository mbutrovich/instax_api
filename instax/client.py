"""Client for Instax SHARE printers that join over Wi-Fi."""

import logging
import socket
import struct
import time
from collections.abc import Collection, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from os import PathLike

from PIL import Image

from instax.errors import (
    InstaxError,
    PrinterError,
    PrintTimeoutError,
    ProtocolError,
    UnsupportedPrinterError,
)
from instax.image import Fit, encode_image, prepare_image
from instax.protocol import (
    Opcode,
    Response,
    ReturnCode,
    Specifications,
    Version,
    decode_response,
    describe_return_code,
    encode_command,
    lock_payload,
    read_frame,
    transfer_start_payload,
    unpack_payload,
)

logger = logging.getLogger(__name__)

DEFAULT_HOST = "192.168.0.251"
DEFAULT_PORT = 8080
DEFAULT_PIN = 1111

# Seconds between status checks while the printer is busy.
POLL_INTERVAL = 1.0
# The printer needs this many seconds between the end of a transfer and the print start.
TRANSFER_SETTLE_TIME = 1.0
# Seconds to wait for a busy printer before giving up on starting a print.
READY_TIMEOUT = 30.0
# A print may take up to three times the printer's own estimate, but no less than this.
MIN_PRINT_TIMEOUT = 30.0

RAW_RGB_FORMAT = 16
# Chunk size to use when the printer's transfer start reply does not give one.
DEFAULT_CHUNK_SIZE = 480
# The SP-1 takes JPEG data with model-specific color correction, which is not implemented.
UNSUPPORTED_MODELS = {"SP-1"}

BUSY = frozenset({ReturnCode.PRINTING, ReturnCode.EJECTING})
PRINT_FINISHED = frozenset({ReturnCode.OK, ReturnCode.FILM_EMPTY})
STILL_PRINTING = frozenset({ReturnCode.PRINTING, ReturnCode.HOLD})


@dataclass(frozen=True)
class PrinterInfo:
    """What the printer reports about itself."""

    model: str
    firmware: str
    hardware: str
    battery_level: int
    """Charge level from 0 to 3."""
    charging: bool
    """Whether the printer is charging over USB."""
    film_remaining: int
    print_count: int
    width: int
    height: int


class _Connection:
    """One TCP connection to the printer, sending one command at a time."""

    def __init__(self, sock: socket.socket, session_id: int, pin: int):
        self._sock = sock
        self._session_id = session_id
        self._pin = pin

    def send(self, opcode: Opcode, payload: bytes = b"", *, allow: Collection[int] = ()) -> Response:
        """Send a command and return the reply.

        Raises PrinterError unless the return code is OK or listed in ``allow``.
        """
        frame = encode_command(opcode, self._session_id, self._pin, payload)
        logger.debug("sending %s: %s", opcode.name, frame[:32].hex(" "))
        self._sock.sendall(frame)
        reply = read_frame(self._sock)
        if not reply:
            raise ProtocolError("the printer closed the connection")
        logger.debug("received: %s", reply.hex(" "))
        response = decode_response(reply, opcode=opcode, session_id=self._session_id)
        if response.return_code != ReturnCode.OK and response.return_code not in allow:
            raise PrinterError(describe_return_code(response.return_code), response.return_code)
        return response


class Printer:
    """An Instax SHARE SP-2 or SP-3 printer.

    The computer must be on the printer's Wi-Fi network, whose name starts with
    ``INSTAX-``. Each method opens its own connections, so a Printer can be reused.

    >>> printer = Printer()                      # doctest: +SKIP
    >>> printer.print_image("photo.jpg")         # doctest: +SKIP
    """

    def __init__(
        self, host: str = DEFAULT_HOST, port: int = DEFAULT_PORT, pin: int = DEFAULT_PIN, timeout: float = 15.0
    ):
        if not 0 <= pin <= 9999:
            raise ValueError(f"PIN must be between 0 and 9999, not {pin}")
        self.host = host
        self.port = port
        self.pin = pin
        self.timeout = timeout
        self._session_id = int(time.time() * 1000) & 0xFFFFFFFF

    @contextmanager
    def _connect(self) -> Iterator[_Connection]:
        with socket.create_connection((self.host, self.port), timeout=self.timeout) as sock:
            yield _Connection(sock, self._session_id, self.pin)

    def info(self) -> PrinterInfo:
        """Return the printer's model, versions, battery, film and print size."""
        with self._connect() as connection:
            model = _model_name(connection)
            version = Version.from_payload(connection.send(Opcode.VERSION).payload)
            specs = Specifications.from_payload(connection.send(Opcode.SPECIFICATIONS).payload)
            count = connection.send(Opcode.PRINT_COUNT)
        return PrinterInfo(
            model=model,
            firmware=version.firmware,
            hardware=version.hardware,
            battery_level=count.battery_level,
            charging=count.charging,
            film_remaining=count.film_remaining,
            print_count=unpack_payload(">I", count.payload)[0],
            width=specs.width,
            height=specs.height,
        )

    def print_image(self, image: Image.Image | str | PathLike, fit: Fit = "crop") -> None:
        """Print an image or image file and wait until the print is finished.

        See :func:`instax.image.prepare_image` for how ``fit`` sizes the image.
        """
        if not isinstance(image, Image.Image):
            with Image.open(image) as opened:
                self.print_image(opened, fit)
            return

        self._set_lock(True)
        try:
            self._print(image, fit)
        finally:
            try:
                self._set_lock(False)
            except (InstaxError, OSError) as e:
                logger.warning("Could not unlock the printer: %s", e)

    def _set_lock(self, locked: bool) -> None:
        """Lock the printer to this client, or release it.

        The printer releases the lock by itself 60 seconds after this client's last command.
        """
        with self._connect() as connection:
            connection.send(Opcode.LOCK, lock_payload(locked))

    def _print(self, image: Image.Image, fit: Fit) -> None:
        with self._connect() as connection:
            model = _model_name(connection)
            if model in UNSUPPORTED_MODELS:
                raise UnsupportedPrinterError(f"the {model} is not supported")
            _check_ready(connection.send(Opcode.PRINT_COUNT))
            specs = Specifications.from_payload(connection.send(Opcode.SPECIFICATIONS).payload)
            connection.send(Opcode.RESET)

        data = encode_image(prepare_image(image, specs.width, specs.height, fit))
        logger.info("Sending a %dx%d image to the %s", specs.width, specs.height, model)
        with self._connect() as connection:
            _transfer(connection, data)
        transfer_end = time.monotonic()

        with self._connect() as connection:
            _send_when_idle(connection, Opcode.VERSION, check_ejecting=True)
            time.sleep(max(0.0, transfer_end + TRANSFER_SETTLE_TIME - time.monotonic()))
            reply = _send_when_idle(connection, Opcode.PRINT_START)
        estimate = unpack_payload(">I", reply.payload)[0] / 10 if len(reply.payload) >= 4 else 0.0
        logger.info("Printing, which should take about %.0f seconds", estimate)
        self._wait_for_print(estimate)
        logger.info("Print finished")

    def _wait_for_print(self, estimate: float) -> None:
        deadline = time.monotonic() + max(3 * estimate, MIN_PRINT_TIMEOUT)
        while True:
            time.sleep(POLL_INTERVAL)
            with self._connect() as connection:
                response = connection.send(Opcode.PRINT_STATUS, allow=STILL_PRINTING | PRINT_FINISHED)
            if response.return_code in PRINT_FINISHED:
                return
            if time.monotonic() >= deadline:
                raise PrintTimeoutError("the printer did not report that the print finished")


def _model_name(connection: _Connection) -> str:
    return connection.send(Opcode.MODEL_NAME).payload.decode("ascii", errors="replace").rstrip("\0")


def _check_ready(response: Response) -> None:
    if response.cover_open:
        raise PrinterError("the film cover is open")
    if response.film_empty:
        raise PrinterError(describe_return_code(ReturnCode.FILM_EMPTY), ReturnCode.FILM_EMPTY)


def _transfer(connection: _Connection, data: bytes) -> None:
    reply = connection.send(Opcode.TRANSFER_START, transfer_start_payload(RAW_RGB_FORMAT, 0, len(data)))
    chunk_size = unpack_payload(">H", reply.payload, 2)[0] if len(reply.payload) >= 4 else DEFAULT_CHUNK_SIZE
    if chunk_size == 0:
        raise ProtocolError("the printer asked for a chunk size of 0")
    for index, start in enumerate(range(0, len(data), chunk_size)):
        # Every chunk is sent at full size. The image length in the transfer start tells the
        # printer where the zero padding of the last chunk begins.
        chunk = data[start : start + chunk_size].ljust(chunk_size, b"\0")
        connection.send(Opcode.SEND_CHUNK, struct.pack(">I", index) + chunk)
    connection.send(Opcode.TRANSFER_END)


def _send_when_idle(connection: _Connection, opcode: Opcode, *, check_ejecting: bool = False) -> Response:
    """Send a command, repeating it while the printer reports that it is busy."""
    deadline = time.monotonic() + READY_TIMEOUT
    while True:
        response = connection.send(opcode, allow=BUSY)
        if response.return_code not in BUSY and not (check_ejecting and response.ejecting):
            return response
        if time.monotonic() >= deadline:
            raise PrinterError("the printer stayed busy", response.return_code)
        time.sleep(POLL_INTERVAL)
