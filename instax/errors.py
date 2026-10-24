"""Exceptions raised by the library."""


class InstaxError(Exception):
    """Base class for all errors raised by this library."""


class ProtocolError(InstaxError):
    """A frame was malformed or did not match the request it answers."""


class PrinterError(InstaxError):
    """The printer reported a problem, such as no film or a wrong PIN."""

    def __init__(self, message: str, return_code: int | None = None):
        super().__init__(message)
        self.return_code = return_code


class UnsupportedPrinterError(InstaxError):
    """The printer model uses an image format this library cannot produce."""


class PrintTimeoutError(InstaxError, TimeoutError):
    """The printer did not finish printing in time."""
