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


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:  # noqa: ARG001
    """Register the actions once for the whole integration."""
    from .services import async_setup_services  # noqa: PLC0415

    async_setup_services(hass)
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
    from .repairs import async_check_core_conflict  # noqa: PLC0415

    # Core `onkyo` on the same host would push this connection off (one per host).
    async_check_core_conflict(hass, entry)
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

    # The sidebar page stays across a reload (a name change reloads the entry); it goes in
    # ``async_remove_entry``.
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_remove_entry(hass: HomeAssistant, entry: OnkyoConfigEntry) -> None:
    """Remove the card from the dashboards when the last receiver goes."""
    from .frontend import async_remove_frontend, async_update_panel  # noqa: PLC0415
    from .repairs import async_clear_core_conflict  # noqa: PLC0415

    async_clear_core_conflict(hass, entry)
    await async_update_panel(hass, entry.entry_id, show=False)
    await async_remove_frontend(hass, entry)
