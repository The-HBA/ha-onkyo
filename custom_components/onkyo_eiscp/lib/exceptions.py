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


class CiRefusedError(EiscpError):
    """A CI (config) write that the library refuses to send: read-only or unknown settings."""

    def __init__(self, code: str, reason: str) -> None:
        """Remember which family was refused and why."""
        super().__init__(f"CI {code} write refused: {reason}")
        self.code = code
        self.reason = reason


class CiNotAppliedError(EiscpError):
    """A CI set was sent but the record read back without the new value (ignored)."""

    def __init__(self, code: str, message: str, change: object = None) -> None:
        """Remember which family and message had no effect, and the ``CiChange`` if any.

        ``change`` (with ``after``) lets the caller restore the fields that did apply.
        """
        super().__init__(f"CI {code} set had no effect: {message!r}")
        self.code = code
        self.message = message
        self.change = change
