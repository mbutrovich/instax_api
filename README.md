# instax_api
[![Build, Lint and Test](https://github.com/mbutrovich/instax_api/actions/workflows/python-test.yml/badge.svg)](https://github.com/mbutrovich/instax_api/actions/workflows/python-test.yml)
[![Coverage Status](https://coveralls.io/repos/github/mbutrovich/instax_api/badge.svg?branch=main)](https://coveralls.io/github/mbutrovich/instax_api?branch=main)

A Python library and command line tool to print photos on the Fujifilm Instax SHARE SP-2 and SP-3 printers over Wi-Fi.

This is a fork of [jpwsutton/instax_api](https://github.com/jpwsutton/instax_api), which is archived. It has been tested on an SP-3. The `instax-api` package on PyPI is the original project, not this fork.

## Install

With [uv](https://docs.astral.sh/uv/):

```
uv tool install git+https://github.com/mbutrovich/instax_api
```

This installs the `instax-print` command. From a clone of this repository, run `uv tool install .` instead, or use `uv run instax-print` without installing.

## Printing

Turn the printer on and join its Wi-Fi network, whose name starts with `INSTAX-` followed by 8 digits. Then run:

```
instax-print photo.jpg
```

The printer reports its own print size, so the same command works for the SP-2 and the SP-3. By default the photo is cropped to fill the print. Use `--fit contain` to print the whole photo with white bars instead.

Other options:

- `--pin 1234` sets the printer's PIN if you changed it from the default of 1111.
- `--info` shows the model, firmware, battery level, film remaining and lifetime print count.
- `--preview out.png` saves the image as it would be printed, without connecting. Add `--size 600x800` for the SP-2.
- `-v` logs every frame sent and received.

### Hints and tips

- If your computer has a static IP address, switch to DHCP before printing. The printer assigns an address when you join its network.
- The printer turns itself off after about 10 minutes without use.
- The thick edge of the print is the bottom of the image. Rotate landscape photos before printing them, or they are cropped to portrait.

## Library

```python
from instax import Printer

printer = Printer(pin=1111)
print(printer.info())
printer.print_image("photo.jpg", fit="contain")
```

`print_image` also accepts a Pillow `Image`. Errors reported by the printer, such as an empty film pack or a wrong PIN, raise `instax.PrinterError`. Network failures raise `OSError`.

## Development

See [docs/development.md](docs/development.md) for setting up a development environment and running the tests and the simulator, and [docs/protocol.md](docs/protocol.md) for how the printer protocol works.
