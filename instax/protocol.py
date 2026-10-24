"""Frame format of the Instax SHARE Wi-Fi protocol.

Every exchange is one command frame from the client and one response frame from the
printer. All integers are big-endian. A command frame is::

    0x24, opcode, length (u16), session id (u32), PIN (u16), 0x0000, payload,
    checksum (u16), 0x0D 0x0A

A response frame is::

    0x2A, opcode, length (u16), session id (u32), 4 unknown bytes, return code,
    1 unknown byte, eject flags, status, payload, checksum (u16), 0x0D 0x0A

The length counts the whole frame. The checksum is the bitwise NOT of the 16-bit sum
of every byte before it.
"""

import socket
import struct
from dataclasses import dataclass
from enum import IntEnum

from instax.errors import ProtocolError

COMMAND_START = 0x24
RESPONSE_START = 0x2A
COMMAND_HEADER_SIZE = 12
RESPONSE_HEADER_SIZE = 16
TRAILER = b"\r\n"
TRAILER_SIZE = 4
MAX_FRAME_SIZE = 0xFFFF


class Opcode(IntEnum):
    """Known command opcodes."""

    SPECIFICATIONS = 0x4F
    RESET = 0x50
    TRANSFER_START = 0x51
    SEND_CHUNK = 0x52
    TRANSFER_END = 0x53
    PRINT_START = 0xB0
    LOCK = 0xB3
    POWER_OFF = 0xB4
    CHANGE_PIN = 0xB6
    VERSION = 0xC0
    PRINT_COUNT = 0xC1
    MODEL_NAME = 0xC2
    PRINT_STATUS = 0xC3
    FUNCTION_VERSION = 0xC4


class ReturnCode(IntEnum):
    """Known return codes in response frames."""

    OK = 0x00
    HOLD = 0x7F
    OTHER_CLIENT = 0xA0
    NOT_IMAGE_DATA = 0xA1
    BATTERY_EMPTY = 0xA2
    PRINTING = 0xA3
    EJECTING = 0xA4
    TESTING = 0xA5
    CHARGING = 0xB4
    CONNECT_ERROR = 0xE0
    FRAME_ERROR_1 = 0xF0
    FRAME_ERROR_2 = 0xF1
    FRAME_ERROR_3 = 0xF2
    FRAME_ERROR_4 = 0xF3
    FILM_EMPTY = 0xF4
    CAM_POINT = 0xF5
    MOTOR = 0xF6
    WRONG_PIN = 0xF7
    PI_SENSOR = 0xF8


RETURN_CODE_MESSAGES = {
    ReturnCode.HOLD: "the printer is busy",
    ReturnCode.OTHER_CLIENT: "another device is using the printer",
    ReturnCode.NOT_IMAGE_DATA: "the printer rejected the image data",
    ReturnCode.BATTERY_EMPTY: "the battery is empty",
    ReturnCode.PRINTING: "the printer is printing",
    ReturnCode.EJECTING: "the printer is ejecting a print",
    ReturnCode.TESTING: "the printer is in test mode",
    ReturnCode.CHARGING: "the printer is charging",
    ReturnCode.CONNECT_ERROR: "the printer reported a connection error",
    ReturnCode.FRAME_ERROR_1: "the printer could not read the command",
    ReturnCode.FRAME_ERROR_2: "the printer could not read the command",
    ReturnCode.FRAME_ERROR_3: "the printer could not read the command",
    ReturnCode.FRAME_ERROR_4: "the printer could not read the command",
    ReturnCode.FILM_EMPTY: "the printer is out of film",
    ReturnCode.CAM_POINT: "the print mechanism reported an error",
    ReturnCode.MOTOR: "the motor reported an error",
    ReturnCode.WRONG_PIN: "the PIN is wrong",
    ReturnCode.PI_SENSOR: "a sensor reported an error",
}


def describe_return_code(code: int) -> str:
    """Return a readable message for a return code, including unknown ones."""
    return RETURN_CODE_MESSAGES.get(code, f"the printer returned error code 0x{code:02X}")


def checksum(data: bytes) -> int:
    return ~sum(data) & 0xFFFF


def _frame(header: bytes, payload: bytes) -> bytes:
    body = header + payload
    return body + struct.pack(">H", checksum(body)) + TRAILER


def _frame_length(payload: bytes, header_size: int) -> int:
    length = header_size + len(payload) + TRAILER_SIZE
    if length > MAX_FRAME_SIZE:
        raise ValueError(f"frame of {length} bytes exceeds the maximum of {MAX_FRAME_SIZE}")
    return length


def encode_command(opcode: int, session_id: int, pin: int, payload: bytes = b"") -> bytes:
    """Build a command frame."""
    length = _frame_length(payload, COMMAND_HEADER_SIZE)
    return _frame(struct.pack(">BBHIHxx", COMMAND_START, opcode, length, session_id, pin), payload)


def encode_response(
    opcode: int,
    session_id: int,
    payload: bytes = b"",
    *,
    return_code: int = ReturnCode.OK,
    ejecting: bool = False,
    cover_open: bool = False,
    battery: int = 0,
    film: int = 0,
) -> bytes:
    """Build a response frame. The status arguments describe the printer's state."""
    length = _frame_length(payload, RESPONSE_HEADER_SIZE)
    eject_flags = 0x04 if ejecting else 0
    status = (0x80 if cover_open else 0) | (battery & 0x07) << 4 | film & 0x0F
    header = struct.pack(">BBHI4xBxBB", RESPONSE_START, opcode, length, session_id, return_code, eject_flags, status)
    return _frame(header, payload)


def frame_length(header: bytes) -> int:
    """Return the total frame length from the first four bytes of a frame."""
    return struct.unpack_from(">H", header, 2)[0]


def _check_frame(data: bytes, start: int, header_size: int) -> None:
    if len(data) < header_size + TRAILER_SIZE:
        raise ProtocolError(f"frame of {len(data)} bytes is too short")
    if data[0] != start:
        raise ProtocolError(f"unexpected start byte 0x{data[0]:02X}")
    if frame_length(data) != len(data):
        raise ProtocolError(f"length field says {frame_length(data)} bytes but the frame has {len(data)}")
    if data[-2:] != TRAILER:
        raise ProtocolError("frame does not end with the expected trailer")
    if struct.unpack_from(">H", data, len(data) - TRAILER_SIZE)[0] != checksum(data[:-TRAILER_SIZE]):
        raise ProtocolError("checksum mismatch")


@dataclass(frozen=True)
class Command:
    """A decoded command frame."""

    opcode: int
    session_id: int
    pin: int
    payload: bytes


@dataclass(frozen=True)
class Response:
    """A decoded response frame."""

    opcode: int
    session_id: int
    return_code: int
    ejecting: bool
    cover_open: bool
    battery: int
    """Raw 3-bit battery state. See ``battery_level`` and ``charging``."""
    film: int
    """Raw film count. Values above 10 mean the printer is out of film."""
    payload: bytes

    @property
    def battery_level(self) -> int:
        """Charge level from 0 to 3."""
        return self.battery & 0x03

    @property
    def charging(self) -> bool:
        """Whether the printer is charging over USB."""
        return bool(self.battery & 0x04)

    @property
    def film_empty(self) -> bool:
        return self.film > 10

    @property
    def film_remaining(self) -> int:
        return 0 if self.film_empty else self.film


def decode_command(data: bytes) -> Command:
    """Decode and validate a command frame."""
    _check_frame(data, COMMAND_START, COMMAND_HEADER_SIZE)
    opcode, session_id, pin = struct.unpack_from(">xBxxIH", data)
    return Command(opcode, session_id, pin, bytes(data[COMMAND_HEADER_SIZE:-TRAILER_SIZE]))


def decode_response(data: bytes, *, opcode: int | None = None, session_id: int | None = None) -> Response:
    """Decode and validate a response frame.

    If ``opcode`` or ``session_id`` is given, the response must match it.
    """
    _check_frame(data, RESPONSE_START, RESPONSE_HEADER_SIZE)
    response_opcode, response_session, return_code, eject_flags, status = struct.unpack_from(">xBxxI4xBxBB", data)
    if opcode is not None and response_opcode != opcode:
        raise ProtocolError(f"expected a reply to opcode 0x{opcode:02X} but got 0x{response_opcode:02X}")
    if session_id is not None and response_session != session_id:
        raise ProtocolError(f"expected session id 0x{session_id:08X} but got 0x{response_session:08X}")
    return Response(
        opcode=response_opcode,
        session_id=response_session,
        return_code=return_code,
        ejecting=bool(eject_flags & 0x04),
        cover_open=bool(status & 0x80),
        battery=status >> 4 & 0x07,
        film=status & 0x0F,
        payload=bytes(data[RESPONSE_HEADER_SIZE:-TRAILER_SIZE]),
    )


def read_frame(sock: socket.socket) -> bytes:
    """Read one frame from a socket.

    Returns ``b""`` if the peer closed the connection before sending anything.
    """
    header = _recv_exactly(sock, 4)
    if not header:
        return b""
    if len(header) < 4:
        raise ProtocolError("connection closed in the middle of a frame")
    length = frame_length(header)
    if length < 4:
        raise ProtocolError(f"length field of {length} bytes is too short")
    body = _recv_exactly(sock, length - 4)
    if len(body) < length - 4:
        raise ProtocolError("connection closed in the middle of a frame")
    return header + body


def _recv_exactly(sock: socket.socket, size: int) -> bytes:
    data = bytearray()
    while len(data) < size:
        chunk = sock.recv(size - len(data))
        if not chunk:
            break
        data += chunk
    return bytes(data)


def unpack_payload(fmt: str, payload: bytes, offset: int = 0) -> tuple:
    """Unpack fields from a payload, raising ProtocolError if it is too short."""
    try:
        return struct.unpack_from(fmt, payload, offset)
    except struct.error as e:
        raise ProtocolError(f"payload of {len(payload)} bytes is too short") from e


@dataclass(frozen=True)
class Specifications:
    """The image size and transfer limits the printer reports."""

    width: int
    height: int
    colours: int
    chunk_size: int

    @classmethod
    def from_payload(cls, payload: bytes) -> "Specifications":
        width, height, colours = unpack_payload(">HHH", payload)
        (chunk_size,) = unpack_payload(">H", payload, 12)
        return cls(width, height, colours, chunk_size)


@dataclass(frozen=True)
class Version:
    """Firmware and hardware versions, formatted as two hex bytes such as ``01.13``."""

    firmware: str
    hardware: str

    @classmethod
    def from_payload(cls, payload: bytes) -> "Version":
        _, firmware, hardware = unpack_payload(">HHH", payload)
        return cls(f"{firmware >> 8:02X}.{firmware & 0xFF:02X}", f"{hardware >> 8:02X}.{hardware & 0xFF:02X}")


def lock_payload(locked: bool) -> bytes:
    """Build the payload that locks the printer to this client or releases it."""
    return struct.pack(">B3x", 1 if locked else 0)


def transfer_start_payload(image_format: int, options: int, length: int) -> bytes:
    """Build the payload that announces an image transfer."""
    return struct.pack(">BBI6x", image_format, options, length)
