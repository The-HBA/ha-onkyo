"""Home Assistant integration for Onkyo, Pioneer and Integra network receivers (eISCP).

Home Assistant imports stay inside the functions: importing the ``lib`` subpackage (the
survey tool and the simulator do) runs this file first and must not need Home Assistant.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.typing import ConfigType

    from .coordinator import OnkyoCoordinator

    type OnkyoConfigEntry = ConfigEntry[OnkyoCoordinator]


async def async_setup(hass: HomeAssistant, _config: ConfigType) -> bool:
    """Register the card's websocket commands."""
    from .websocket import async_register_commands  # noqa: PLC0415

    async_register_commands(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: OnkyoConfigEntry) -> bool:
    """Connect to the receiver and set up its entities."""
    from homeassistant.const import CONF_HOST, CONF_PORT  # noqa: PLC0415

    from .const import (  # noqa: PLC0415
        CONF_RESTORE_VOLUME,
        DEFAULT_PORT,
        DEFAULT_RESTORE_VOLUME,
        PLATFORMS,
    )
    from .coordinator import OnkyoCoordinator  # noqa: PLC0415
    from .frontend import async_setup_frontend, async_update_panel  # noqa: PLC0415
    from .lib import Receiver  # noqa: PLC0415

    # The card and the sidebar page; the receiver is not needed to serve them.
    await async_setup_frontend(hass)
    await async_update_panel(hass, entry.entry_id, show=True)
    receiver = Receiver(
        entry.data[CONF_HOST],
        entry.data.get(CONF_PORT, DEFAULT_PORT),
        restore_volume=entry.options.get(CONF_RESTORE_VOLUME, DEFAULT_RESTORE_VOLUME),
    )
    coordinator = OnkyoCoordinator(hass, entry, receiver)
    await coordinator.async_start()
    entry.async_on_unload(coordinator.async_stop)
    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: OnkyoConfigEntry) -> bool:
    """Unload the entities and close the connection."""
    from .const import PLATFORMS  # noqa: PLC0415

    from .frontend import async_update_panel  # noqa: PLC0415

    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        await async_update_panel(hass, entry.entry_id, show=False)
    return unloaded


async def async_remove_entry(hass: HomeAssistant, entry: OnkyoConfigEntry) -> None:
    """Remove the card from the dashboards when the last receiver goes."""
    from .frontend import async_remove_frontend  # noqa: PLC0415

    await async_remove_frontend(hass, entry)
