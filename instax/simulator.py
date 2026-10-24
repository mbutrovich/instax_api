"""A fake printer for tests and for trying the client without hardware.

Run ``python -m instax.simulator`` to start one on port 8080.
"""

import argparse
import logging
import socketserver
import struct
import threading
import time
from pathlib import Path

from instax.errors import ProtocolError
from instax.image import decode_image
from instax.protocol import (
    Opcode,
    ReturnCode,
    decode_command,
    encode_response,
    read_frame,
    unpack_payload,
)

logger = logging.getLogger(__name__)

SIZES = {"SP-2": (600, 800), "SP-3": (800, 800)}


class Simulator:
    """A printer that answers the commands the client sends.

    It keeps every image it receives in ``images`` and every opcode in ``opcodes``.
    Use it as a context manager to serve on a background thread.
    """

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 0,
        *,
        model: str = "SP-3",
        width: int = 800,
        height: int = 800,
        chunk_size: int = 60000,
        report_chunk_size: bool = True,
        pin: int = 1111,
        battery: int = 3,
        film: int = 10,
        cover_open: bool = False,
        print_count: int = 20,
        print_time: int = 100,
        print_polls: int = 1,
        print_result: int = ReturnCode.OK,
        start_busy: int = 0,
        lock_timeout: float = 60.0,
        save_dir: Path | None = None,
    ):
        """Create a simulator.

        ``print_time`` is the print estimate in tenths of a second. ``print_polls``
        is how many status polls report printing before ``print_result``.
        ``start_busy`` is how many print start commands are refused as busy.
        While a session holds the lock, commands from other sessions are refused.
        The lock expires ``lock_timeout`` seconds after the holder's last command.
        Each accepted lock command appends its state to ``lock_history``.
        """
        self.model = model
        self.width = width
        self.height = height
        self.chunk_size = chunk_size
        self.report_chunk_size = report_chunk_size
        self.pin = pin
        self.battery = battery
        self.film = film
        self.cover_open = cover_open
        self.print_count = print_count
        self.print_time = print_time
        self.print_polls = print_polls
        self.print_result = print_result
        self.start_busy = start_busy
        self.lock_timeout = lock_timeout
        self.save_dir = save_dir
        self.images: list[bytes] = []
        self.opcodes: list[int] = []
        self.lock_history: list[bool] = []
        self._lock = threading.Lock()
        self._expected_length = 0
        self._received = bytearray()
        self._polls_left = 0
        self._lock_holder: int | None = None
        self._lock_expiry = 0.0
        self._server = _Server((host, port), self)
        self._thread: threading.Thread | None = None

    @property
    def address(self) -> tuple[str, int]:
        host, port = self._server.server_address[:2]
        return host, port

    def __enter__(self) -> "Simulator":
        # A short poll interval makes shutdown() return quickly.
        self._thread = threading.Thread(target=self._server.serve_forever, args=(0.01,), daemon=True)
        self._thread.start()
        return self

    def __exit__(self, *exc_info) -> None:
        self._server.shutdown()
        self._server.server_close()

    def serve_forever(self) -> None:
        self._server.serve_forever()

    def respond(self, frame: bytes) -> bytes:
        """Return the response frame for a command frame."""
        command = decode_command(frame)
        with self._lock:
            self.opcodes.append(command.opcode)
            if command.pin != self.pin:
                return_code, payload = ReturnCode.WRONG_PIN, b""
            elif self._locked_by_other(command.session_id):
                return_code, payload = ReturnCode.OTHER_CLIENT, b""
            else:
                return_code, payload = self._handle(command.opcode, command.session_id, command.payload)
        return encode_response(
            command.opcode,
            command.session_id,
            payload,
            return_code=return_code,
            cover_open=self.cover_open,
            battery=self.battery,
            film=self.film,
        )

    def _locked_by_other(self, session_id: int) -> bool:
        """Return whether another session holds the lock, extending it if this one does."""
        now = time.monotonic()
        if self._lock_holder is not None and now >= self._lock_expiry:
            self._lock_holder = None
        if self._lock_holder is None:
            return False
        if self._lock_holder != session_id:
            return True
        self._lock_expiry = now + self.lock_timeout
        return False

    def _handle(self, opcode: int, session_id: int, payload: bytes) -> tuple[int, bytes]:
        ok = ReturnCode.OK
        if opcode == Opcode.MODEL_NAME:
            return ok, self.model.encode("ascii")
        if opcode == Opcode.VERSION:
            return ok, struct.pack(">HHH2x", 0x0101, 0x0113, 0)
        if opcode == Opcode.SPECIFICATIONS:
            return ok, struct.pack(">HHHH4xHBxI8x", self.width, self.height, 256, 10, self.chunk_size, 16, 0)
        if opcode == Opcode.PRINT_COUNT:
            return ok, struct.pack(">I12x", self.print_count)
        if opcode == Opcode.LOCK:
            locked = unpack_payload(">B", payload)[0] == 1
            self.lock_history.append(locked)
            self._lock_holder = session_id if locked else None
            self._lock_expiry = time.monotonic() + self.lock_timeout
            return ok, b""
        if opcode == Opcode.RESET:
            return ok, b""
        if opcode == Opcode.TRANSFER_START:
            (self._expected_length,) = unpack_payload(">I", payload, 2)
            self._received = bytearray()
            return ok, struct.pack(">2xH", self.chunk_size) if self.report_chunk_size else b""
        if opcode == Opcode.SEND_CHUNK:
            self._received += payload[4:]
            return ok, payload[:4]
        if opcode == Opcode.TRANSFER_END:
            self._finish_image(bytes(self._received[: self._expected_length]))
            return ok, b""
        if opcode == Opcode.PRINT_START:
            if self.start_busy > 0:
                self.start_busy -= 1
                return ReturnCode.PRINTING, b""
            self._polls_left = self.print_polls
            return ok, struct.pack(">I", self.print_time)
        if opcode == Opcode.PRINT_STATUS:
            if self._polls_left > 0:
                self._polls_left -= 1
                return ReturnCode.HOLD, b""
            return self.print_result, b""
        return ReturnCode.FRAME_ERROR_1, b""

    def _finish_image(self, data: bytes) -> None:
        self.images.append(data)
        if self.save_dir is not None:
            path = self.save_dir / time.strftime("%Y%m%d-%H%M%S.png")
            decode_image(data, self.width, self.height).save(path)
            logger.info("Saved the received image to %s", path)


class _Handler(socketserver.BaseRequestHandler):
    server: "_Server"

    def handle(self) -> None:
        try:
            while frame := read_frame(self.request):
                self.request.sendall(self.server.simulator.respond(frame))
        except (ProtocolError, OSError) as e:
            logger.warning("Dropping connection: %s", e)


class _Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True

    def __init__(self, address: tuple[str, int], simulator: Simulator):
        self.simulator = simulator
        super().__init__(address, _Handler)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="instax-simulator", description="Run a fake Instax SHARE printer.")
    parser.add_argument("--host", default="0.0.0.0", help="address to listen on (default: %(default)s)")
    parser.add_argument("--port", type=int, default=8080, help="port to listen on (default: %(default)s)")
    parser.add_argument("--model", choices=sorted(SIZES), default="SP-3", help="model to report (default: %(default)s)")
    parser.add_argument("--pin", type=int, default=1111, help="PIN to accept (default: %(default)s)")
    parser.add_argument("--save-dir", type=Path, help="save each received image as a PNG in this directory")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    width, height = SIZES[args.model]
    simulator = Simulator(
        args.host, args.port, model=args.model, width=width, height=height, pin=args.pin, save_dir=args.save_dir
    )
    logger.info("Simulating an %s on %s:%d", args.model, *simulator.address)
    try:
        simulator.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
