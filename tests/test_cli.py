"""Tests for the command line interface."""

import pytest
from PIL import Image

from instax import cli, client
from instax.simulator import Simulator


@pytest.fixture(autouse=True)
def no_waiting(monkeypatch):
    monkeypatch.setattr(client, "POLL_INTERVAL", 0)
    monkeypatch.setattr(client, "TRANSFER_SETTLE_TIME", 0)


@pytest.fixture
def photo(tmp_path):
    path = tmp_path / "photo.png"
    Image.new("RGB", (10, 10), (255, 0, 0)).save(path)
    return str(path)


def address_args(simulator):
    host, port = simulator.address
    return ["--host", host, "--port", str(port)]


def test_print(photo):
    with Simulator(width=16, height=16) as simulator:
        assert cli.main([*address_args(simulator), photo]) == 0
    assert len(simulator.images) == 1


def test_info(capsys):
    with Simulator(model="SP-3") as simulator:
        assert cli.main([*address_args(simulator), "--info"]) == 0
    assert "SP-3" in capsys.readouterr().out


def test_error_exit_code(photo, capsys):
    with Simulator(pin=1234) as simulator:
        assert cli.main([*address_args(simulator), photo]) == 1
    assert "PIN" in capsys.readouterr().err


def test_preview_does_not_connect(photo, tmp_path):
    output = tmp_path / "preview.png"
    assert cli.main(["--preview", str(output), "--size", "800x800", photo]) == 0
    with Image.open(output) as preview:
        assert preview.size == (800, 800)


def test_image_required():
    with pytest.raises(SystemExit):
        cli.main([])
