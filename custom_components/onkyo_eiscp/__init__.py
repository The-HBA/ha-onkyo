"""Home Assistant integration for Onkyo, Pioneer and Integra network receivers (eISCP)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.const import CONF_HOST, CONF_PORT, Platform

from .const import CONF_RESTORE_VOLUME, DEFAULT_PORT, DEFAULT_RESTORE_VOLUME
from .coordinator import OnkyoCoordinator
from .lib import Receiver

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant

type OnkyoConfigEntry = ConfigEntry[OnkyoCoordinator]

#: The platforms built so far; P3.S1 adds select, number, switch, sensor and remote.
SETUP_PLATFORMS = (Platform.MEDIA_PLAYER,)


async def async_setup_entry(hass: HomeAssistant, entry: OnkyoConfigEntry) -> bool:
    """Connect to the receiver and set up its entities."""
    receiver = Receiver(
        entry.data[CONF_HOST],
        entry.data.get(CONF_PORT, DEFAULT_PORT),
        restore_volume=entry.options.get(CONF_RESTORE_VOLUME, DEFAULT_RESTORE_VOLUME),
    )
    coordinator = OnkyoCoordinator(hass, entry, receiver)
    await coordinator.async_start()
    entry.async_on_unload(coordinator.async_stop)
    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, SETUP_PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: OnkyoConfigEntry) -> bool:
    """Unload the entities and close the connection."""
    return await hass.config_entries.async_unload_platforms(entry, SETUP_PLATFORMS)
