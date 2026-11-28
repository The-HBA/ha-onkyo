"""The coordinator: the receiver pushes, the coordinator forwards (ARCHITECTURE.md C4)."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .const import DOMAIN
from .lib import EiscpError

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant

    from .lib import Capabilities, Receiver
    from .lib.ci import CiRecord

_LOGGER = logging.getLogger(__name__)

#: Reported in ``ReceiverData.changed`` after a reconnect: every entity refreshes.
EVERYTHING: Final = "*"


def _nothing() -> None:
    """Stand in for the receiver's listener remover before ``async_start``."""


@dataclass(frozen=True, slots=True)
class ReceiverData:
    """One snapshot of the receiver."""

    connected: bool
    values: Mapping[str, str]
    unavailable: frozenset[str]
    changed: frozenset[str]
    """Codes changed since the last snapshot; ``{"*"}`` after a reconnect."""
    capabilities: Capabilities


class OnkyoCoordinator(DataUpdateCoordinator[ReceiverData]):
    """Holds the entry's one ``Receiver`` and turns its pushes into snapshots."""

    config_entry: ConfigEntry

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, receiver: Receiver) -> None:
        """Remember the receiver; ``async_start`` connects it."""
        super().__init__(hass, _LOGGER, config_entry=entry, name=DOMAIN, update_interval=None)
        self.receiver = receiver
        self._supported: frozenset[str] = frozenset()
        self._reloaded = False
        self._remove_listener: Callable[[], None] = _nothing
        # CI settings (sidebar page): one operation at a time, whether the receiver answers
        # them (``None`` until probed), and the values a calibration record held before the
        # first change of this session, so the page can offer "restore".
        self.ci_lock = asyncio.Lock()
        self.ci_supported: bool | None = None
        self.ci_baseline: dict[tuple[str, tuple[tuple[str, str], ...]], CiRecord] = {}

    async def async_start(self) -> None:
        """Connect, probe and publish the first snapshot."""
        try:
            capabilities = await self.receiver.start()
        except (EiscpError, OSError, TimeoutError) as err:
            msg = f"Cannot reach the receiver at {self.receiver.host}: {err}"
            raise ConfigEntryNotReady(msg) from err
        self._supported = capabilities.supported
        self._remove_listener = self.receiver.add_listener(self._on_change)
        self.async_set_updated_data(self._snapshot(frozenset({EVERYTHING})))

    async def async_stop(self) -> None:
        """Stop listening and close the connection."""
        self._remove_listener()
        await self.receiver.stop()

    def _snapshot(self, changed: frozenset[str]) -> ReceiverData:
        receiver = self.receiver
        return ReceiverData(
            connected=receiver.connected,
            values=dict(receiver.values),
            unavailable=receiver.unavailable,
            changed=changed,
            capabilities=receiver.capabilities,
        )

    def _on_change(self, changed: frozenset[str]) -> None:
        data = self._snapshot(changed)
        self.async_set_updated_data(data)
        grown = data.capabilities.supported - self._supported
        if data.connected and grown and not self._reloaded:
            # The first probe ran in standby; entities must follow what the receiver really has.
            self._reloaded = True
            _LOGGER.debug("Supported codes changed; reloading the entry once")
            self.hass.config_entries.async_schedule_reload(self.config_entry.entry_id)
