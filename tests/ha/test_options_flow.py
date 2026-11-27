"""Options flow: rename, hide, order, volume."""

from __future__ import annotations

from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.onkyo_eiscp.const import (
    CONF_INPUT_ORDER,
    CONF_INPUTS,
    CONF_LISTENING_MODES,
    CONF_MAX_VOLUME,
    CONF_RESTORE_VOLUME,
)
from tests.ha.conftest import setup

ENTITY = "media_player.onkyo_tx_rz50"


async def _menu(hass: HomeAssistant, flow_id: str, step: str) -> Any:
    return await hass.config_entries.options.async_configure(flow_id, {"next_step_id": step})


async def _rename_input(
    hass: HomeAssistant, flow_id: str, code: str, user: dict[str, Any], *, first: bool = False
) -> Any:
    if first:
        await _menu(hass, flow_id, "inputs")
    result = await hass.config_entries.options.async_configure(flow_id, {"input": code})
    assert result["step_id"] == "input_edit"
    return await hass.config_entries.options.async_configure(flow_id, user)


async def test_rename_hide_order_and_volume_are_saved(
    hass: HomeAssistant, entry: MockConfigEntry
) -> None:
    await setup(hass, entry)
    caps = entry.runtime_data.data.capabilities
    by_name = {item.name: item.code for item in caps.inputs}
    movie, ps5, htpc = by_name["Movie"], by_name["PS5"], by_name["HTPC"]

    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.MENU
    flow_id = result["flow_id"]

    result = await _rename_input(
        hass, flow_id, movie, {"name": "Film", "hidden": False}, first=True
    )
    assert result["step_id"] == "inputs"
    result = await _rename_input(hass, flow_id, ps5, {"name": "", "hidden": True})
    assert result["step_id"] == "inputs"
    await hass.config_entries.options.async_configure(flow_id, {})  # back to the menu

    await _menu(hass, flow_id, "input_order")
    await hass.config_entries.options.async_configure(flow_id, {CONF_INPUT_ORDER: [htpc, movie]})

    await _menu(hass, flow_id, "listening_modes")
    result = await hass.config_entries.options.async_configure(flow_id, {"mode": "00"})
    assert result["step_id"] == "mode_edit"
    await hass.config_entries.options.async_configure(
        flow_id, {"name": "Plain Stereo", "hidden": False}
    )
    await hass.config_entries.options.async_configure(flow_id, {})

    await _menu(hass, flow_id, "volume")
    result = await hass.config_entries.options.async_configure(
        flow_id, {CONF_MAX_VOLUME: -32, CONF_RESTORE_VOLUME: False}
    )
    result = await _menu(hass, flow_id, "save")
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()

    assert entry.options[CONF_INPUTS] == {
        movie: {"name": "Film", "hidden": False},
        ps5: {"hidden": True, "name": ""},
    }
    assert entry.options[CONF_LISTENING_MODES]["00"]["name"] == "Plain Stereo"
    assert entry.options[CONF_INPUT_ORDER] == [htpc, movie]
    assert entry.options[CONF_MAX_VOLUME] == 100
    assert entry.options[CONF_RESTORE_VOLUME] is False
    attributes = hass.states.get(ENTITY).attributes  # type: ignore[union-attr]
    assert attributes["source_list"][:2] == ["HTPC", "Film"]
    assert "PS5" not in attributes["source_list"]
    assert "Plain Stereo" in attributes["sound_mode_list"]


async def test_name_must_be_unique(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    await setup(hass, entry)
    caps = entry.runtime_data.data.capabilities
    by_name = {item.name: item.code for item in caps.inputs}
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await _rename_input(
        hass, result["flow_id"], by_name["Movie"], {"name": "PS5", "hidden": False}, first=True
    )
    assert result["step_id"] == "input_edit"
    assert result["errors"] == {"name": "name_in_use"}


async def test_empty_name_resets_and_unchanged_is_not_stored(
    hass: HomeAssistant, entry: MockConfigEntry
) -> None:
    await setup(hass, entry)
    movie = next(i.code for i in entry.runtime_data.data.capabilities.inputs if i.name == "Movie")
    result = await hass.config_entries.options.async_init(entry.entry_id)
    flow_id = result["flow_id"]
    await _rename_input(hass, flow_id, movie, {"name": "Film", "hidden": False}, first=True)
    await _rename_input(hass, flow_id, movie, {"name": "", "hidden": False})
    await hass.config_entries.options.async_configure(flow_id, {})
    result = await _menu(hass, flow_id, "save")
    assert result["data"][CONF_INPUTS] == {}


async def test_mode_name_must_be_unique(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    await setup(hass, entry)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    flow_id = result["flow_id"]
    await _menu(hass, flow_id, "listening_modes")
    await hass.config_entries.options.async_configure(flow_id, {"mode": "00"})
    result = await hass.config_entries.options.async_configure(
        flow_id, {"name": "Direct", "hidden": False}
    )
    assert result["errors"] == {"name": "name_in_use"}


async def test_options_need_a_loaded_entry(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    entry.add_to_hass(hass)  # never set up: not loaded
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "not_loaded"


async def test_lowest_maximum_volume_is_kept(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    await setup(hass, entry)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    flow_id = result["flow_id"]
    await _menu(hass, flow_id, "volume")
    await hass.config_entries.options.async_configure(
        flow_id, {CONF_MAX_VOLUME: -81.5, CONF_RESTORE_VOLUME: True}
    )
    result = await _menu(hass, flow_id, "save")
    assert result["data"][CONF_MAX_VOLUME] == 1
