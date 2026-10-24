"""Tests for frame encoding and decoding."""

import pytest

from instax.errors import ProtocolError
from instax.protocol import (
    MAX_FRAME_SIZE,
    Opcode,
    ReturnCode,
    Specifications,
    Version,
    decode_command,
    decode_response,
    encode_command,
    encode_response,
    lock_payload,
    transfer_start_payload,
)

# Frames from the original project's test suite. The varying session ids and
# payloads suggest they were captured from an SP-2.
COMMANDS = {
    "model name": "24c2 0010 0b8d c2b4 0457 0000 fca0 0d0a",
    "function version": "24c4 0014 4e40 684c 0457 0000 0000 0008 fd5e 0d0a",
    "lock": "24b3 0014 9619 02df 0457 0000 0100 0000 fd28 0d0a",
    "reset": "2450 0010 96c9 aada 0457 0000 fc3d 0d0a",
    "transfer start": "2451 001c 9b60 d511 0457 0000 1000 0015 f900 0000 0000 0000 fc14 0d0a",
    "transfer end": "2453 0010 c9a9 b71e 0457 0000 fcd6 0d0a",
    "print start": "24b0 0010 f776 ecbe 0457 0000 fba9 0d0a",
    "print status": "24c3 0010 f130 d7cc 0457 0000 fbe9 0d0a",
}

RESPONSES = {
    "specifications": "2a4f 0030 e759 eede 0000 0000 0000 0027 0258 0320 0100 000a 0000 0000 ea60 1000"
    " 0000 0000 0000 0000 0000 0000 fa41 0d0a",
    "version": "2ac0 001c e759 eede 0000 0000 0000 0027 0101 0113 0000 0000 fbb0 0d0a",
    "print count": "2ac1 0024 e759 eede 0000 0000 0000 0027 0000 0003 00f3 c048 0000 1645 001e 0000 f946 0d0a",
    "lock": "2ab3 0014 75b8 bd8e 0000 0000 0000 003a fc5c 0d0a",
    "reset": "2a50 0014 75b8 bd8e 0000 0000 0000 003a fcbf 0d0a",
    "send chunk": "2a52 0018 75b8 bd8e 0000 0000 0000 003a 0000 0014 fca5 0d0a",
    "transfer end": "2a53 0014 75b8 bd8e 0000 0000 0000 003a fcbc 0d0a",
    "print start": "2ab0 0018 f130 d7cc 0000 0000 0000 0036 0000 0064 fbaf 0d0a",
    "print status busy": "2ac3 0014 f130 d7cc 0000 0000 7f00 0436 fb81 0d0a",
    "print status done": "2ac3 0014 f130 d7cc 0000 0000 0000 0035 fc05 0d0a",
}


def frame(hex_string):
    return bytes.fromhex(hex_string)


@pytest.mark.parametrize("hex_string", COMMANDS.values(), ids=COMMANDS.keys())
def test_command_round_trip(hex_string):
    command = decode_command(frame(hex_string))
    assert command.pin == 1111
    assert encode_command(command.opcode, command.session_id, command.pin, command.payload) == frame(hex_string)


@pytest.mark.parametrize("hex_string", RESPONSES.values(), ids=RESPONSES.keys())
def test_response_round_trip(hex_string):
    response = decode_response(frame(hex_string))
    encoded = encode_response(
        response.opcode,
        response.session_id,
        response.payload,
        return_code=response.return_code,
        ejecting=response.ejecting,
        cover_open=response.cover_open,
        battery=response.battery,
        film=response.film,
    )
    assert encoded == frame(hex_string)


def test_decode_command():
    command = decode_command(frame(COMMANDS["model name"]))
    assert command.opcode == Opcode.MODEL_NAME
    assert command.session_id == 0x0B8DC2B4
    assert command.payload == b""


def test_lock_payload():
    assert decode_command(frame(COMMANDS["lock"])).payload == lock_payload(True)
    assert lock_payload(False) == bytes(4)


def test_transfer_start_payload():
    command = decode_command(frame(COMMANDS["transfer start"]))
    assert command.payload == transfer_start_payload(16, 0, 1440000)


def test_decode_response_status():
    busy = decode_response(frame(RESPONSES["print status busy"]))
    assert busy.opcode == Opcode.PRINT_STATUS
    assert busy.return_code == ReturnCode.HOLD
    assert busy.ejecting
    assert not busy.cover_open
    assert busy.battery == 3
    assert busy.film == 6

    done = decode_response(frame(RESPONSES["print status done"]))
    assert done.return_code == ReturnCode.OK
    assert not done.ejecting
    assert done.film == 5


@pytest.mark.parametrize("film, remaining, empty", [(0, 0, False), (10, 10, False), (11, 0, True), (15, 0, True)])
def test_film_count(film, remaining, empty):
    response = decode_response(encode_response(Opcode.VERSION, 1, film=film))
    assert response.film_remaining == remaining
    assert response.film_empty == empty


@pytest.mark.parametrize(
    "battery, level, charging",
    [(0, 0, False), (1, 1, False), (3, 3, False), (4, 0, True), (5, 1, True), (7, 3, True)],
)
def test_battery(battery, level, charging):
    response = decode_response(encode_response(Opcode.VERSION, 1, battery=battery))
    assert (response.battery_level, response.charging) == (level, charging)


def test_status_bits_are_independent():
    response = decode_response(encode_response(Opcode.VERSION, 1, ejecting=True, cover_open=True, battery=7, film=15))
    assert (response.ejecting, response.cover_open, response.battery, response.film) == (True, True, 7, 15)


def test_specifications():
    specs = Specifications.from_payload(decode_response(frame(RESPONSES["specifications"])).payload)
    assert specs == Specifications(width=600, height=800, colours=256, chunk_size=60000)


def test_version():
    version = Version.from_payload(decode_response(frame(RESPONSES["version"])).payload)
    assert version == Version(firmware="01.13", hardware="00.00")


@pytest.mark.parametrize("parser", [Specifications.from_payload, Version.from_payload])
def test_short_payload(parser):
    with pytest.raises(ProtocolError):
        parser(b"\x00\x01")


def test_largest_frame_round_trip():
    payload = bytes(range(256)) * ((MAX_FRAME_SIZE - 16) // 256) + bytes((MAX_FRAME_SIZE - 16) % 256)
    encoded = encode_command(Opcode.SEND_CHUNK, 0xFFFFFFFF, 9999, payload)
    assert len(encoded) == MAX_FRAME_SIZE
    assert decode_command(encoded).payload == payload


def test_oversized_frame():
    with pytest.raises(ValueError):
        encode_command(Opcode.SEND_CHUNK, 1, 1111, bytes(MAX_FRAME_SIZE - 15))


def test_bad_checksum():
    data = bytearray(frame(RESPONSES["version"]))
    data[-3] ^= 1
    with pytest.raises(ProtocolError, match="checksum"):
        decode_response(bytes(data))


def test_bad_trailer():
    data = bytearray(frame(RESPONSES["version"]))
    data[-1] = 0
    with pytest.raises(ProtocolError, match="trailer"):
        decode_response(bytes(data))


def test_wrong_direction():
    with pytest.raises(ProtocolError, match="start byte"):
        decode_response(frame(COMMANDS["lock"]))
    with pytest.raises(ProtocolError, match="start byte"):
        decode_command(frame(RESPONSES["reset"]))


def test_length_mismatch():
    with pytest.raises(ProtocolError, match="length"):
        decode_response(frame(RESPONSES["version"])[:-1])


@pytest.mark.parametrize("size", [0, 1, 15, 19])
def test_truncated_response(size):
    with pytest.raises(ProtocolError):
        decode_response(frame(RESPONSES["reset"])[:size])


def test_unexpected_reply():
    data = frame(RESPONSES["reset"])
    assert decode_response(data, opcode=Opcode.RESET, session_id=0x75B8BD8E).opcode == Opcode.RESET
    with pytest.raises(ProtocolError, match="opcode"):
        decode_response(data, opcode=Opcode.VERSION)
    with pytest.raises(ProtocolError, match="session"):
        decode_response(data, session_id=1)


def test_unknown_opcode_and_return_code_are_kept():
    response = decode_response(encode_response(0x40, 1, return_code=0x99))
    assert response.opcode == 0x40
    assert response.return_code == 0x99
