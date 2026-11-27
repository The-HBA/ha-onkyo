"""The main zone media player against the simulated TX-RZ50."""

from __future__ import annotations

import pytest
from homeassistant.components.media_player import (
    ATTR_INPUT_SOURCE,
    ATTR_MEDIA_VOLUME_LEVEL,
    ATTR_MEDIA_VOLUME_MUTED,
    ATTR_SOUND_MODE,
    SERVICE_SELECT_SOUND_MODE,
    SERVICE_SELECT_SOURCE,
)
from homeassistant.components.media_player import (
    DOMAIN as MEDIA_PLAYER,
)
from homeassistant.const import (
    ATTR_ENTITY_ID,
    SERVICE_TURN_OFF,
    SERVICE_VOLUME_DOWN,
    SERVICE_VOLUME_MUTE,
    SERVICE_VOLUME_SET,
    SERVICE_VOLUME_UP,
    STATE_OFF,
    STATE_ON,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.onkyo_eiscp.const import CONF_INPUTS, CONF_LISTENING_MODES, CONF_MAX_VOLUME
from custom_components.onkyo_eiscp.lib.commands import LISTENING_MODES
from tests.ha.conftest import MAC, poll_state, setup

ENTITY = "media_player.onkyo_tx_rz50"


async def test_main_player(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    await setup(hass, entry)
    state = hass.states.get(ENTITY)
    assert state is not None
    assert state.state == STATE_ON
    registry = er.async_get(hass)
    assert registry.async_get(ENTITY).unique_id == f"{MAC}-main-main"  # type: ignore[union-attr]


async def test_source_list_is_clean_and_unique(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    await setup(hass, entry)
    sources = hass.states.get(ENTITY).attributes["source_list"]  # type: ignore[union-attr]
    assert len(sources) > 5
    assert len(sources) == len(set(sources))
    assert not any("···" in name for name in sources)


async def test_sound_mode_list_is_clean_and_unique(
    hass: HomeAssistant, entry: MockConfigEntry
) -> None:
    await setup(hass, entry)
    attributes = hass.states.get(ENTITY).attributes  # type: ignore[union-attr]
    modes = attributes["sound_mode_list"]
    assert len(modes) >= 15
    assert len(modes) == len(set(modes))
    table = {mode.name for mode in LISTENING_MODES.values()}
    assert attributes["sound_mode"] in modes
    assert set(modes) <= table | {attributes["sound_mode"]}
    assert len(attributes["sound_mode_codes"]) == len(modes)


async def test_rename_hide_and_order(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    await setup(hass, entry)
    caps = entry.runtime_data.data.capabilities
    by_name = {item.name: item.code for item in caps.inputs}
    movie, ps5, htpc = by_name["Movie"], by_name["PS5"], by_name["HTPC"]
    await hass.config_entries.async_unload(entry.entry_id)
    hass.config_entries.async_update_entry(
        entry,
        options={
            CONF_INPUTS: {
                movie: {"name": "Film", "hidden": False},
                ps5: {"name": "", "hidden": True},
            },
            CONF_LISTENING_MODES: {
                "00": {"name": "Plain Stereo", "hidden": False},
                "0F": {"name": "", "hidden": True},
            },
            "input_order": [htpc, movie],
        },
    )
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    attributes = hass.states.get(ENTITY).attributes  # type: ignore[union-attr]
    sources = attributes["source_list"]
    assert sources[:2] == ["HTPC", "Film"]
    assert "PS5" not in sources
    assert attributes["source"] == "Film"
    modes = attributes["sound_mode_list"]
    assert "Plain Stereo" in modes
    assert "Mono" not in modes
    assert "Stereo" not in modes


async def test_select_source_and_mode_by_clean_name(
    hass: HomeAssistant, entry: MockConfigEntry
) -> None:
    await setup(hass, entry)
    await hass.services.async_call(
        MEDIA_PLAYER,
        SERVICE_SELECT_SOURCE,
        {ATTR_ENTITY_ID: ENTITY, ATTR_INPUT_SOURCE: "HTPC"},
        blocking=True,
    )
    await hass.services.async_call(
        MEDIA_PLAYER,
        SERVICE_SELECT_SOUND_MODE,
        {ATTR_ENTITY_ID: ENTITY, ATTR_SOUND_MODE: "Direct"},
        blocking=True,
    )
    await poll_state(hass, "source", "HTPC")
    await poll_state(hass, "sound_mode", "Direct")


async def test_power_mute_and_volume_steps(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    await setup(hass, entry)
    before = hass.states.get(ENTITY).attributes["volume_level"]  # type: ignore[union-attr]
    await hass.services.async_call(
        MEDIA_PLAYER, SERVICE_VOLUME_UP, {ATTR_ENTITY_ID: ENTITY}, blocking=True
    )
    await poll_state(hass, "volume_level", pytest.approx(before + 0.01))
    await hass.services.async_call(
        MEDIA_PLAYER, SERVICE_VOLUME_DOWN, {ATTR_ENTITY_ID: ENTITY}, blocking=True
    )
    await poll_state(hass, "volume_level", pytest.approx(before))
    await hass.services.async_call(
        MEDIA_PLAYER,
        SERVICE_VOLUME_MUTE,
        {ATTR_ENTITY_ID: ENTITY, ATTR_MEDIA_VOLUME_MUTED: True},
        blocking=True,
    )
    await poll_state(hass, "is_volume_muted", True)
    await hass.services.async_call(
        MEDIA_PLAYER, SERVICE_TURN_OFF, {ATTR_ENTITY_ID: ENTITY}, blocking=True
    )
    await poll_state(hass, None, STATE_OFF)


async def test_max_volume_option_scales_and_clamps(
    hass: HomeAssistant, entry: MockConfigEntry
) -> None:
    entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(entry, options={CONF_MAX_VOLUME: 100})
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    state = hass.states.get(ENTITY)
    assert state is not None
    assert state.attributes["volume_level"] == pytest.approx(0.76)
    await hass.services.async_call(
        MEDIA_PLAYER,
        SERVICE_VOLUME_SET,
        {ATTR_ENTITY_ID: ENTITY, ATTR_MEDIA_VOLUME_LEVEL: 1.0},
        blocking=True,
    )
    await poll_state(hass, "volume_db", -32.0)
    assert hass.states.get(ENTITY).attributes["volume_level"] == pytest.approx(1.0)  # type: ignore[union-attr]


async def test_set_volume_clamped(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    await setup(hass, entry)
    await hass.services.async_call(
        MEDIA_PLAYER,
        SERVICE_VOLUME_SET,
        {ATTR_ENTITY_ID: ENTITY, ATTR_MEDIA_VOLUME_LEVEL: 0.3},
        blocking=True,
    )
    await hass.async_block_till_done()
    state = hass.states.get(ENTITY)
    assert state is not None
    assert state.attributes["volume_level"] == pytest.approx(0.3, abs=0.01)
    assert "volume_db" in state.attributes


async def test_unknown_source_is_a_validation_error(
    hass: HomeAssistant, entry: MockConfigEntry
) -> None:
    await setup(hass, entry)
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            MEDIA_PLAYER,
            SERVICE_SELECT_SOURCE,
            {ATTR_ENTITY_ID: ENTITY, ATTR_INPUT_SOURCE: "No Such Input"},
            blocking=True,
        )
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            MEDIA_PLAYER,
            SERVICE_SELECT_SOUND_MODE,
            {ATTR_ENTITY_ID: ENTITY, ATTR_SOUND_MODE: "No Such Mode"},
            blocking=True,
        )
