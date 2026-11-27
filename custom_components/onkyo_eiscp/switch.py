"""Switches: Music Optimizer and Cinema Filter."""

from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.components.switch import SwitchEntity

from .setting import OnkyoSetting

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

    from . import OnkyoConfigEntry
    from .coordinator import OnkyoCoordinator

PARALLEL_UPDATES = 1

ROWS = (("music_optimizer", "MOT"), ("cinema_filter", "RAS"))
_ON = "01"
_OFF = "00"


async def async_setup_entry(
    hass: HomeAssistant,  # noqa: ARG001
    entry: OnkyoConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add the switches whose code the receiver answered."""
    coordinator = entry.runtime_data
    supported = coordinator.data.capabilities.supported
    async_add_entities(
        OnkyoSwitch(coordinator, key, code) for key, code in ROWS if code in supported
    )


class OnkyoSwitch(OnkyoSetting, SwitchEntity):
    """A 00/01 code. ``MOT`` is refused outside Stereo, which makes it unavailable then."""

    def __init__(self, coordinator: OnkyoCoordinator, key: str, code: str) -> None:
        """Create the switch."""
        super().__init__(coordinator, key, code)

    @property
    def is_on(self) -> bool | None:
        """Return True while the receiver reports 01."""
        param = self._param
        return None if param is None else param == _ON

    async def async_turn_on(self, **kwargs: object) -> None:  # noqa: ARG002
        """Turn the setting on."""
        await self._send(_ON)

    async def async_turn_off(self, **kwargs: object) -> None:  # noqa: ARG002
        """Turn the setting off."""
        await self._send(_OFF)
