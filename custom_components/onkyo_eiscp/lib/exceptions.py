"""Errors raised by the eISCP library."""

from __future__ import annotations


class EiscpError(Exception):
    """Base class for every library error."""


class FrameError(EiscpError):
    """A packet from the receiver is not valid eISCP."""


class ConnectionClosedError(EiscpError):
    """The connection is closed, or the receiver closed it."""


class CodecError(EiscpError, ValueError):
    """A value cannot be decoded or encoded."""


class NotAvailableError(EiscpError):
    """The receiver answered ``N/A``: the setting is not available now."""

    def __init__(self, code: str, param: str = "") -> None:
        """Remember which message was refused."""
        super().__init__(f"{code}{param} is not available (N/A)")
        self.code = code
        self.param = param


class NoReplyError(EiscpError):
    """No answer in time: an ignored set, a silent code, or the receiver just after power-on."""

    def __init__(self, code: str, param: str = "") -> None:
        """Remember which message got no answer."""
        super().__init__(f"no reply to {code}{param}")
        self.code = code
        self.param = param
