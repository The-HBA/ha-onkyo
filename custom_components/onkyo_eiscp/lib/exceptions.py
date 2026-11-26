"""Errors raised by the eISCP library."""

from __future__ import annotations


class EiscpError(Exception):
    """Base class for every library error."""


class FrameError(EiscpError):
    """A packet from the receiver is not valid eISCP."""


class ConnectionClosedError(EiscpError):
    """The connection is closed, or the receiver closed it."""
