# instax_api
[![.github/workflows/python-test.yml](https://github.com/jpwsutton/instax_api/actions/workflows/python-test.yml/badge.svg)](https://github.com/jpwsutton/instax_api/actions/workflows/python-test.yml)
[![Coverage Status](https://img.shields.io/coveralls/jpwsutton/instax_api/master.svg)](https://coveralls.io/github/jpwsutton/instax_api?branch=master)

A Python library and command line tool to print photos on the Fujifilm Instax SHARE SP-2 and SP-3 printers over Wi-Fi.

## Install

From a clone of this repository, with [uv](https://docs.astral.sh/uv/):

```
uv tool install .
```

This installs the `instax-print` command. To run it from the clone without installing, use `uv run instax-print`.

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
