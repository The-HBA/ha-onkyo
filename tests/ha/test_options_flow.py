"""Options flow: the volume limits only (names, hiding and order go through the card's sheet)."""

from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.onkyo_eiscp.const import (
    CONF_INPUT_ORDER,
    CONF_INPUTS,
    CONF_MAX_VOLUME,
    CONF_RESTORE_VOLUME,
)
from tests.ha.conftest import setup


async def test_volume_is_saved_and_names_are_kept(
    hass: HomeAssistant, entry: MockConfigEntry
) -> None:
    entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        entry,
        options={CONF_INPUTS: {"10": {"name": "Film", "hidden": False}}, CONF_INPUT_ORDER: ["05"]},
    )
    await setup(hass, entry)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "init"
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_MAX_VOLUME: -32, CONF_RESTORE_VOLUME: False}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    assert entry.options[CONF_MAX_VOLUME] == 100
    assert entry.options[CONF_RESTORE_VOLUME] is False
    assert entry.options[CONF_INPUTS] == {"10": {"name": "Film", "hidden": False}}
    assert entry.options[CONF_INPUT_ORDER] == ["05"]


async def test_top_volume_drops_the_limit(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(entry, options={CONF_MAX_VOLUME: 100})
    await setup(hass, entry)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_MAX_VOLUME: 18, CONF_RESTORE_VOLUME: True}
    )
    assert CONF_MAX_VOLUME not in result["data"]
    assert result["data"][CONF_RESTORE_VOLUME] is True


async def test_options_need_a_loaded_entry(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    entry.add_to_hass(hass)  # never set up: not loaded
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "not_loaded"


async def test_lowest_maximum_volume_is_kept(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    await setup(hass, entry)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_MAX_VOLUME: -81.5, CONF_RESTORE_VOLUME: True}
    )
    assert result["data"][CONF_MAX_VOLUME] == 1
