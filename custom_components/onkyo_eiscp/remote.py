"""The remote entity: main zone power and the on-screen menu keys (``OSD``)."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

from homeassistant.components.remote import ATTR_DELAY_SECS, ATTR_NUM_REPEATS, RemoteEntity
from homeassistant.exceptions import ServiceValidationError

from .const import DOMAIN
from .lib import COMMANDS
from .setting import POWER, POWER_ON, OnkyoSetting

if TYPE_CHECKING:
    from collections.abc import Iterable

    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

    from . import OnkyoConfigEntry
    from .coordinator import OnkyoCoordinator

PARALLEL_UPDATES = 1

KEYS = {key: param for param, key in COMMANDS["OSD"].options.items()}
DEFAULT_DELAY = 0.2


async def async_setup_entry(
    hass: HomeAssistant,  # noqa: ARG001
    entry: OnkyoConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add the remote when the receiver answers power (OSD itself has no query)."""
    coordinator = entry.runtime_data
    if POWER in coordinator.data.capabilities.supported:
        async_add_entities([OnkyoRemote(coordinator)])


class OnkyoRemote(OnkyoSetting, RemoteEntity):
    """On or off follows the main zone power; ``send_command`` sends OSD keys."""

    needs_power = False

    def __init__(self, coordinator: OnkyoCoordinator) -> None:
        """Create the remote."""
        super().__init__(coordinator, "remote", POWER)
        self._command = COMMANDS["OSD"]

    @property
    def available(self) -> bool:
        """Return True while the receiver is connected (power on is a key too)."""
        return self.coordinator.data.connected

    @property
    def is_on(self) -> bool | None:
        """Return True while the main zone is on."""
        param = self._param
        return None if param is None else param == POWER_ON

    async def async_turn_on(self, **kwargs: Any) -> None:  # noqa: ARG002, ANN401
        """Power the receiver on."""
        await self._send("01")

    async def async_turn_off(self, **kwargs: Any) -> None:  # noqa: ARG002, ANN401
        """Put the receiver in standby."""
        await self._send("00")

    async def async_send_command(self, command: Iterable[str], **kwargs: Any) -> None:  # noqa: ANN401
        """Send keys: up, down, left, right, enter, exit, menu, home, quick, audio, video."""
        keys = [str(key).lower() for key in command]
        for key in keys:
            if key not in KEYS:
                raise ServiceValidationError(
                    translation_domain=DOMAIN,
                    translation_key="unknown_remote_key",
                    translation_placeholders={"name": key},
                )
        repeats = int(kwargs.get(ATTR_NUM_REPEATS, 1))
        delay = float(kwargs.get(ATTR_DELAY_SECS, DEFAULT_DELAY))
        for round_number in range(repeats):
            for index, key in enumerate(keys):
                if round_number or index:
                    await asyncio.sleep(delay)
                await self._send(KEYS[key], "OSD")
