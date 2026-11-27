"""Setup, unload, availability, diagnostics and the reload rule."""

from __future__ import annotations

from unittest.mock import patch

from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.components.diagnostics import (
    get_diagnostics_for_config_entry,
)
from pytest_homeassistant_custom_component.typing import ClientSessionGenerator

from custom_components.onkyo_eiscp.const import DOMAIN
from tests.ha.conftest import MAC, setup
from tools.eiscp_sim import SimServer

ENTITY = "media_player.onkyo_tx_rz50"


async def test_device_registry(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    await setup(hass, entry)
    device = dr.async_get(hass).async_get_device_by_identifier((DOMAIN, MAC), entry.entry_id)
    assert device is not None
    assert device.manufacturer == "Onkyo"
    assert device.model == "TX-RZ50"
    assert device.name == "Onkyo TX-RZ50"
    assert not device.connections


async def test_unload_closes_the_connection(
    hass: HomeAssistant, entry: MockConfigEntry, sim: SimServer
) -> None:
    await setup(hass, entry)
    assert sim.connection_count == 1
    receiver = entry.runtime_data.receiver
    assert await hass.config_entries.async_unload(entry.entry_id)
    assert entry.state is ConfigEntryState.NOT_LOADED
    assert not receiver.connected


async def test_unreachable_receiver_retries_later(
    hass: HomeAssistant, socket_enabled: None
) -> None:
    dead = MockConfigEntry(domain=DOMAIN, unique_id=MAC, data={"host": "127.0.0.1", "port": 1})
    dead.add_to_hass(hass)
    await hass.config_entries.async_setup(dead.entry_id)
    assert dead.state is ConfigEntryState.SETUP_RETRY


async def test_entity_unavailable_when_connection_drops(
    hass: HomeAssistant, entry: MockConfigEntry, sim: SimServer
) -> None:
    await setup(hass, entry)
    with patch.object(type(entry.runtime_data.receiver), "connected", False):  # noqa: FBT003
        entry.runtime_data.async_set_updated_data(entry.runtime_data._snapshot(frozenset({"*"})))
        await hass.async_block_till_done()
        assert hass.states.get(ENTITY).state == STATE_UNAVAILABLE  # type: ignore[union-attr]


async def test_diagnostics_hide_the_address(
    hass: HomeAssistant, hass_client: ClientSessionGenerator, entry: MockConfigEntry
) -> None:
    await setup(hass, entry)
    result = await get_diagnostics_for_config_entry(hass, hass_client, entry)
    assert result["entry"]["data"]["host"] == "**REDACTED**"
    assert result["capabilities"]["mac"] == "**REDACTED**"
    assert result["capabilities"]["model"] == "TX-RZ50"
    assert "PWR" in result["capabilities"]["supported"]
