"""The select entities against the simulated TX-RZ50."""

from __future__ import annotations

import pytest
from homeassistant.components.media_player import (
    ATTR_SOUND_MODE,
    SERVICE_SELECT_SOUND_MODE,
)
from homeassistant.components.media_player import DOMAIN as MEDIA_PLAYER
from homeassistant.components.select import (
    ATTR_OPTION,
    ATTR_OPTIONS,
    SERVICE_SELECT_OPTION,
)
from homeassistant.components.select import DOMAIN as SELECT
from homeassistant.const import ATTR_ENTITY_ID, STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from tests.ha.conftest import setup
from tests.ha.entity_helpers import entity_id, wait_state

PLAYER = "media_player.onkyo_tx_rz50"


async def choose(hass: HomeAssistant, entity: str, option: str) -> None:
    await hass.services.async_call(
        SELECT,
        SERVICE_SELECT_OPTION,
        {ATTR_ENTITY_ID: entity, ATTR_OPTION: option},
        blocking=True,
    )


async def test_rows_exist_and_hdmi_output_is_off_by_default(
    hass: HomeAssistant, entry: MockConfigEntry
) -> None:
    await setup(hass, entry)
    for key in ("dirac_slot", "late_night", "dimmer", "equalizer", "digital_filter"):
        assert hass.states.get(entity_id(hass, SELECT, key)).state != STATE_UNAVAILABLE  # type: ignore[union-attr]
    hdmi = er.async_get(hass).async_get(entity_id(hass, SELECT, "hdmi_output"))
    assert hdmi is not None
    assert hdmi.disabled_by is er.RegistryEntryDisabler.INTEGRATION
    assert hdmi.entity_category is not None


async def test_dirac_slot_reads_and_writes(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    await setup(hass, entry)
    dirac = entity_id(hass, SELECT, "dirac_slot")
    state = hass.states.get(dirac)
    assert state is not None
    assert state.state == "slot_3"
    assert state.attributes[ATTR_OPTIONS] == ["off", "slot_1", "slot_2", "slot_3"]
    await choose(hass, dirac, "slot_1")
    await wait_state(hass, dirac, "slot_1")
    await choose(hass, dirac, "off")
    await wait_state(hass, dirac, "off")
    await choose(hass, dirac, "slot_3")
    await wait_state(hass, dirac, "slot_3")


async def test_dirac_rejects_an_unknown_option(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    await setup(hass, entry)
    dirac = entity_id(hass, SELECT, "dirac_slot")
    with pytest.raises(HomeAssistantError):
        await hass.services.async_call(
            SELECT,
            SERVICE_SELECT_OPTION,
            {ATTR_ENTITY_ID: dirac, ATTR_OPTION: "slot_9"},
            blocking=True,
        )


async def test_enum_selects_write(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    await setup(hass, entry)
    equalizer = entity_id(hass, SELECT, "equalizer")
    await choose(hass, equalizer, "preset_1")
    await wait_state(hass, equalizer, "preset_1")
    await choose(hass, equalizer, "off")
    await wait_state(hass, equalizer, "off")
    dimmer = entity_id(hass, SELECT, "dimmer")
    assert hass.states.get(dimmer).attributes[ATTR_OPTIONS] == ["bright", "dim", "dark"]  # type: ignore[union-attr]


async def test_model_profile_limits_the_digital_filter(
    hass: HomeAssistant, entry: MockConfigEntry
) -> None:
    await setup(hass, entry)
    options = hass.states.get(entity_id(hass, SELECT, "digital_filter")).attributes[ATTR_OPTIONS]  # type: ignore[union-attr]
    assert options == ["slow", "sharp", "auto"]


async def test_late_night_high_is_refused_with_pcm_and_left_out(
    hass: HomeAssistant, entry: MockConfigEntry
) -> None:
    await setup(hass, entry)
    late = entity_id(hass, SELECT, "late_night")
    assert "high" in hass.states.get(late).attributes[ATTR_OPTIONS]  # type: ignore[union-attr]
    with pytest.raises(HomeAssistantError):
        await choose(hass, late, "high")
    await hass.async_block_till_done()
    state = hass.states.get(late)
    assert state is not None
    assert state.state != STATE_UNAVAILABLE  # one option refused, not the whole select
    assert "high" not in state.attributes[ATTR_OPTIONS]
    assert "low" in state.attributes[ATTR_OPTIONS]


async def test_selects_follow_power(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    await setup(hass, entry)
    dirac = entity_id(hass, SELECT, "dirac_slot")
    await hass.services.async_call(
        "media_player", "turn_off", {ATTR_ENTITY_ID: PLAYER}, blocking=True
    )
    await wait_state(hass, dirac, STATE_UNAVAILABLE)
    await hass.services.async_call(
        "media_player", "turn_on", {ATTR_ENTITY_ID: PLAYER}, blocking=True
    )
    await wait_state(hass, dirac, "slot_3", seconds=15)


async def test_mode_change_keeps_selects_working(
    hass: HomeAssistant, entry: MockConfigEntry
) -> None:
    await setup(hass, entry)
    await hass.services.async_call(
        MEDIA_PLAYER,
        SERVICE_SELECT_SOUND_MODE,
        {ATTR_ENTITY_ID: PLAYER, ATTR_SOUND_MODE: "Stereo"},
        blocking=True,
    )
    await hass.async_block_till_done()
    assert hass.states.get(entity_id(hass, SELECT, "dirac_slot")).state == "slot_3"  # type: ignore[union-attr]
