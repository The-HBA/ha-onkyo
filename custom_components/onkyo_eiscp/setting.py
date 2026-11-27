"""Shared base of the settings, sensors and switches of the main zone (ARCHITECTURE.md C5)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from .const import ZONE_MAIN
from .coordinator import EVERYTHING, OnkyoCoordinator
from .entity import OnkyoEntity, translated_errors
from .lib import COMMANDS
from .lib.codecs import decode
from .lib.exceptions import CodecError

if TYPE_CHECKING:
    from .lib.codecs import Decoded
    from .lib.commands import Command

POWER = "PWR"
POWER_ON = "01"


class OnkyoSetting(OnkyoEntity):
    """An entity of one receiver code.

    It is available while the receiver is connected, the main zone is on (in standby sets and
    most reads answer ``N/A``), the code holds a value and the receiver has not refused it under
    the current listening mode.
    """

    #: Settings and sensors of a zone need the zone on; the remote and diagnostics do not.
    needs_power = True

    def __init__(
        self, coordinator: OnkyoCoordinator, key: str, code: str, *, zone: str = ZONE_MAIN
    ) -> None:
        """Set the identity from ``key`` and remember the code this entity reads."""
        super().__init__(coordinator, zone, key)
        self._code = code
        self._command: Command = COMMANDS[code]
        self._codes = frozenset({code, POWER})

    @property
    def available(self) -> bool:
        """Return True when the receiver can answer for this code right now."""
        data = self.coordinator.data
        if not data.connected:
            return False
        if self.needs_power and data.values.get(POWER) != POWER_ON:
            return False
        return self._code in data.values and self._code not in data.unavailable

    @property
    def _param(self) -> str | None:
        return self.coordinator.data.values.get(self._code)

    def _decoded(self) -> Decoded:
        """Return the code's value decoded, or None when it is missing or unreadable."""
        param = self._param
        if param is None:
            return None
        try:
            return decode(self._command, param)
        except CodecError:
            return None

    def _handle_coordinator_update(self) -> None:
        changed = self.coordinator.data.changed
        if EVERYTHING in changed or self._codes & changed:
            self.async_write_ha_state()

    async def _send(self, param: str, code: str | None = None) -> None:
        """Set a code on the receiver, with library errors turned into translated ones."""
        with translated_errors():
            await self.coordinator.receiver.set(code or self._code, param)
