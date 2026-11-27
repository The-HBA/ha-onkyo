"""The sensors against the simulated TX-RZ50."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

from homeassistant.components.media_player import ATTR_SOUND_MODE, SERVICE_SELECT_SOUND_MODE
from homeassistant.components.media_player import DOMAIN as MEDIA_PLAYER
from homeassistant.components.sensor import DOMAIN as SENSOR
from homeassistant.const import ATTR_ENTITY_ID, STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.onkyo_eiscp.const import TEMPERATURE_INTERVAL
from tests.ha.conftest import setup
from tests.ha.entity_helpers import entity_id, wait_state

PLAYER = "media_player.onkyo_tx_rz50"


async def test_audio_input_summary_and_fields(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    await setup(hass, entry)
    state = hass.states.get(entity_id(hass, SENSOR, "audio_input"))
    assert state is not None
    assert state.state == "PCM 44.1 kHz"
    assert state.attributes["input_port"] == "HDMI 1"
    assert state.attributes["input_format"] == "PCM"
    assert state.attributes["output_channels"] == "6.1 ch"


async def test_video_input_summary_and_fields(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    await setup(hass, entry)
    state = hass.states.get(entity_id(hass, SENSOR, "video_input"))
    assert state is not None
    assert state.state.startswith("1920 x 1080p")
    assert state.attributes["output_resolution"].startswith("1920 x 1080p")


async def test_audio_input_follows_the_signal(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    await setup(hass, entry)
    entity = entity_id(hass, SENSOR, "audio_input")
    await hass.services.async_call(
        MEDIA_PLAYER,
        SERVICE_SELECT_SOUND_MODE,
        {ATTR_ENTITY_ID: PLAYER, ATTR_SOUND_MODE: "Stereo"},
        blocking=True,
    )
    await hass.async_block_till_done()
    assert hass.states.get(entity).attributes["listening_mode"] == "Stereo"  # type: ignore[union-attr]


async def test_info_sensors_are_unavailable_in_standby(
    hass: HomeAssistant, entry: MockConfigEntry
) -> None:
    await setup(hass, entry)
    await hass.services.async_call(
        MEDIA_PLAYER, "turn_off", {ATTR_ENTITY_ID: PLAYER}, blocking=True
    )
    await wait_state(hass, entity_id(hass, SENSOR, "audio_input"), STATE_UNAVAILABLE)


async def test_diagnostic_sensors_are_disabled_by_default(
    hass: HomeAssistant, entry: MockConfigEntry
) -> None:
    await setup(hass, entry)
    registry = er.async_get(hass)
    for key in ("temperature", "front_display"):
        found = registry.async_get(entity_id(hass, SENSOR, key))
        assert found is not None
        assert found.disabled_by is er.RegistryEntryDisabler.INTEGRATION
        assert found.entity_category is er.EntityCategory.DIAGNOSTIC


async def test_enabled_temperature_and_display_read_values(
    hass: HomeAssistant, entry: MockConfigEntry
) -> None:
    await setup(hass, entry)
    registry = er.async_get(hass)
    for key in ("temperature", "front_display"):
        registry.async_update_entity(entity_id(hass, SENSOR, key), disabled_by=None)
    await hass.config_entries.async_reload(entry.entry_id)  # HA reloads only after 30 s
    await hass.async_block_till_done()
    temperature = hass.states.get(entity_id(hass, SENSOR, "temperature"))
    assert temperature is not None
    assert temperature.state == "28.0"
    assert temperature.attributes["unit_of_measurement"] == "°C"
    display = hass.states.get(entity_id(hass, SENSOR, "front_display"))
    assert display is not None
    assert display.state.startswith("Movie")


async def test_temperature_is_polled(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    await setup(hass, entry)
    registry = er.async_get(hass)
    registry.async_update_entity(entity_id(hass, SENSOR, "temperature"), disabled_by=None)
    tracked: list[tuple[Callable[[datetime], Awaitable[None]], timedelta]] = []

    def track(
        _hass: HomeAssistant, action: Callable[[datetime], Awaitable[None]], interval: timedelta
    ) -> Callable[[], None]:
        tracked.append((action, interval))
        return lambda: None

    with patch("custom_components.onkyo_eiscp.sensor.async_track_time_interval", track):
        await hass.config_entries.async_reload(entry.entry_id)  # HA reloads only after 30 s
        await hass.async_block_till_done()
    assert [interval for _, interval in tracked] == [TEMPERATURE_INTERVAL]
    queries: list[str] = []
    receiver = entry.runtime_data.receiver
    original = receiver.query

    async def spy(code: str) -> str:
        queries.append(code)
        return await original(code)

    receiver.query = spy  # type: ignore[method-assign]
    await tracked[0][0](datetime.now(UTC))
    assert queries == ["TPD"]
    await hass.services.async_call(
        MEDIA_PLAYER, "turn_off", {ATTR_ENTITY_ID: PLAYER}, blocking=True
    )
    await wait_state(hass, entity_id(hass, SENSOR, "temperature"), STATE_UNAVAILABLE)
    await tracked[0][0](datetime.now(UTC))
    assert queries == ["TPD"]  # no poll in standby
