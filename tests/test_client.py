"""Tests for the printer client, run against the simulator."""

import pytest
from PIL import Image

from instax import client
from instax.client import Printer
from instax.errors import PrinterError, PrintTimeoutError, UnsupportedPrinterError
from instax.image import encode_image, prepare_image
from instax.protocol import Opcode, ReturnCode
from instax.simulator import Simulator

RED = (255, 0, 0)


@pytest.fixture(autouse=True)
def no_waiting(monkeypatch):
    monkeypatch.setattr(client, "POLL_INTERVAL", 0)
    monkeypatch.setattr(client, "TRANSFER_SETTLE_TIME", 0)


def run(simulator, image=None, fit="crop", **printer_options):
    """Print an image on a simulator."""
    printer = Printer(*simulator.address, **printer_options)
    printer.print_image(image or Image.new("RGB", (10, 10), RED), fit=fit)


def test_info():
    with Simulator(model="SP-3", battery=2, film=7, print_count=42) as simulator:
        info = Printer(*simulator.address).info()
    assert info.model == "SP-3"
    assert info.firmware == "01.13"
    assert info.hardware == "00.00"
    assert info.battery == 2
    assert info.film_remaining == 7
    assert info.print_count == 42
    assert (info.width, info.height) == (800, 800)


@pytest.mark.parametrize("model, width, height", [("SP-2", 600, 800), ("SP-3", 800, 800)])
def test_print_sends_encoded_image(model, width, height):
    image = Image.effect_mandelbrot((300, 200), (-2, -1, 1, 1), 50).convert("RGB")
    with Simulator(model=model, width=width, height=height) as simulator:
        run(simulator, image)
    assert simulator.images == [encode_image(prepare_image(image, width, height))]


def test_print_sequence():
    with Simulator(width=16, height=16, chunk_size=300, print_polls=2) as simulator:
        run(simulator)
    chunks = -(-16 * 16 * 3 // 300)
    assert simulator.opcodes == [
        Opcode.MODEL_NAME,
        Opcode.PRINT_COUNT,
        Opcode.SPECIFICATIONS,
        Opcode.RESET,
        Opcode.TRANSFER_START,
        *[Opcode.SEND_CHUNK] * chunks,
        Opcode.TRANSFER_END,
        Opcode.VERSION,
        Opcode.PRINT_START,
        *[Opcode.PRINT_STATUS] * 3,
    ]


@pytest.mark.parametrize("chunk_size", [1, 7, 768, 769, 60000])
def test_chunking(chunk_size):
    with Simulator(width=16, height=16, chunk_size=chunk_size) as simulator:
        run(simulator, fit="contain")
    assert simulator.images == [encode_image(prepare_image(Image.new("RGB", (10, 10), RED), 16, 16, fit="contain"))]


def test_default_chunk_size():
    # When the transfer start reply has no payload, chunks are 480 bytes.
    with Simulator(width=16, height=16, report_chunk_size=False) as simulator:
        run(simulator)
    assert simulator.opcodes.count(Opcode.SEND_CHUNK) == -(-16 * 16 * 3 // 480)
    assert len(simulator.images[0]) == 16 * 16 * 3


def test_wrong_pin():
    with Simulator(pin=1234) as simulator, pytest.raises(PrinterError) as error:
        run(simulator)
    assert error.value.return_code == ReturnCode.WRONG_PIN
    assert simulator.images == []


def test_custom_pin():
    with Simulator(width=16, height=16, pin=1234) as simulator:
        run(simulator, pin=1234)
    assert len(simulator.images) == 1


@pytest.mark.parametrize("options", [{"film": 15}, {"cover_open": True}], ids=["no film", "cover open"])
def test_not_ready(options):
    with Simulator(**options) as simulator, pytest.raises(PrinterError):
        run(simulator)
    assert Opcode.TRANSFER_START not in simulator.opcodes


def test_print_fails():
    with Simulator(width=16, height=16, print_result=ReturnCode.MOTOR) as simulator:
        with pytest.raises(PrinterError, match="motor") as error:
            run(simulator)
    assert error.value.return_code == ReturnCode.MOTOR


def test_last_sheet_is_success():
    with Simulator(width=16, height=16, print_result=ReturnCode.FILM_EMPTY) as simulator:
        run(simulator)


def test_print_start_retries_while_busy():
    with Simulator(width=16, height=16, start_busy=2) as simulator:
        run(simulator)
    assert simulator.opcodes.count(Opcode.PRINT_START) == 3


def test_print_timeout(monkeypatch):
    monkeypatch.setattr(client, "MIN_PRINT_TIMEOUT", 0)
    with Simulator(width=16, height=16, print_time=0, print_polls=1000) as simulator:
        with pytest.raises(PrintTimeoutError):
            run(simulator)


def test_unsupported_model():
    with Simulator(model="SP-1") as simulator, pytest.raises(UnsupportedPrinterError):
        run(simulator)
    assert simulator.opcodes == [Opcode.MODEL_NAME]


def test_print_from_path(tmp_path):
    path = tmp_path / "photo.png"
    Image.new("RGB", (10, 10), RED).save(path)
    with Simulator(width=16, height=16) as simulator:
        Printer(*simulator.address).print_image(path)
    assert len(simulator.images) == 1
