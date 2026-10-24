# Development Guide


## Developing using uv

* Install uv on your development machine: https://docs.astral.sh/uv/
* Run `uv sync` to create the virtual environment in `.venv` and install all main and dev dependencies.
* Prefix commands with `uv run` to run them in the virtual environment, for example `uv run pytest`.
* Run `uv run pre-commit install` and then `uv run pre-commit install --hook-type commit-msg` to set up the pre-commit checks.

## Layout

* `instax/protocol.py` encodes and decodes frames. Its module docstring describes the frame format.
* `instax/client.py` holds the `Printer` class and the print sequence.
* `instax/image.py` prepares photos and encodes them in the printer's raw image format.
* `instax/simulator.py` is a fake printer that the tests run against.
* `instax/cli.py` is the `instax-print` command.

## Running tests

Run `uv run pytest`. The tests use the simulator, so they need no printer.

## Running the simulator

Run `uv run instax-simulator --save-dir .` to start a fake SP-3 on port 8080 that saves each image it receives as a PNG. Use `--model SP-2` for an SP-2. Then print to it from another terminal:

```
uv run instax-print --host 127.0.0.1 photo.jpg
```

`--host` and `--port` are hidden from `instax-print --help` because only the simulator needs them.

## Inspecting Packets in Wireshark
* Useful filter: `tcp.port == 8080 && tcp.flags.push == 1`
