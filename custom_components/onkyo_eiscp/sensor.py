"""Sensors: audio and video input, temperature and front display."""

from __future__ import annotations

import logging
from dataclasses import asdict
from typing import TYPE_CHECKING, Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.const import EntityCategory, UnitOfTemperature
from homeassistant.helpers.event import async_track_time_interval

from .const import TEMPERATURE_INTERVAL
from .lib import EiscpError
from .lib.codecs import AudioInfo, VideoInfo
from .setting import POWER, POWER_ON, OnkyoSetting

if TYPE_CHECKING:
    from datetime import datetime

    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

    from . import OnkyoConfigEntry
    from .coordinator import OnkyoCoordinator

_LOGGER = logging.getLogger(__name__)

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,  # noqa: ARG001
    entry: OnkyoConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add the sensors whose code the receiver answered."""
    coordinator = entry.runtime_data
    supported = coordinator.data.capabilities.supported
    entities: list[OnkyoSetting] = []
    if "IFA" in supported:
        entities.append(OnkyoInfoSensor(coordinator, "audio_input", "IFA", AudioInfo))
    if "IFV" in supported:
        entities.append(OnkyoInfoSensor(coordinator, "video_input", "IFV", VideoInfo))
    if "TPD" in supported:
        entities.append(OnkyoTemperatureSensor(coordinator))
    if "FLD" in supported:
        entities.append(OnkyoDisplaySensor(coordinator))
    async_add_entities(entities)


class OnkyoInfoSensor(OnkyoSetting, SensorEntity):
    """``IFA`` or ``IFV``: a short summary as state, every field as an attribute."""

    def __init__(
        self,
        coordinator: OnkyoCoordinator,
        key: str,
        code: str,
        kind: type[AudioInfo | VideoInfo],
    ) -> None:
        """Create the sensor for audio or video information."""
        super().__init__(coordinator, key, code)
        self._kind = kind

    def _info(self) -> AudioInfo | VideoInfo | None:
        value = self._decoded()
        return value if isinstance(value, self._kind) else None

    @property
    def native_value(self) -> str | None:
        """Return the short summary, or None while nothing is playing."""
        info = self._info()
        return (info.summary or None) if info is not None else None

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return every field of the information."""
        info = self._info()
        return None if info is None else asdict(info)


class OnkyoTemperatureSensor(OnkyoSetting, SensorEntity):
    """The receiver's temperature; not pushed, so polled while the receiver is on."""

    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False

    def __init__(self, coordinator: OnkyoCoordinator) -> None:
        """Create the temperature sensor."""
        super().__init__(coordinator, "temperature", "TPD")

    @property
    def native_value(self) -> float | None:
        """Return degrees Celsius."""
        value = self._decoded()
        return float(value) if isinstance(value, int | float) else None

    async def async_added_to_hass(self) -> None:
        """Poll every five minutes while this sensor is enabled."""
        await super().async_added_to_hass()
        self.async_on_remove(async_track_time_interval(self.hass, self._poll, TEMPERATURE_INTERVAL))

    async def _poll(self, now: datetime) -> None:  # noqa: ARG002
        data = self.coordinator.data
        if not data.connected or data.values.get(POWER) != POWER_ON:
            return
        try:
            await self.coordinator.receiver.query("TPD")
        except (EiscpError, OSError, TimeoutError) as err:
            _LOGGER.debug("Temperature query failed: %s", err)


class OnkyoDisplaySensor(OnkyoSetting, SensorEntity):
    """The text on the front display."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False
    needs_power = False

    def __init__(self, coordinator: OnkyoCoordinator) -> None:
        """Create the front display sensor."""
        super().__init__(coordinator, "front_display", "FLD")

    @property
    def native_value(self) -> str | None:
        """Return the decoded display text, None while it is blank."""
        value = self._decoded()
        return (value.strip() or None) if isinstance(value, str) else None
