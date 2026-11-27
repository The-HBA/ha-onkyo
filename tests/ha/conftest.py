"""Fixtures for the Home Assistant layer: a simulated TX-RZ50 and a loaded config entry."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Iterator
from functools import partial
from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest
from homeassistant.const import CONF_HOST, CONF_PORT
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.onkyo_eiscp.const import DOMAIN
from custom_components.onkyo_eiscp.lib import Receiver
from tests.lib.lib_helpers import FAST, make_sim

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

    from tools.eiscp_sim import SimServer

MAC = "0009b0000001"


@pytest.fixture(autouse=True)
def _enable_custom_integrations(enable_custom_integrations: None) -> None:
    """Let Home Assistant load custom_components/onkyo_eiscp."""


@pytest.fixture(autouse=True)
def _fast_receiver() -> Iterator[None]:
    """Run the integration's receiver with the short test timings."""
    with patch("custom_components.onkyo_eiscp.Receiver", partial(Receiver, timing=FAST)):
        yield


@pytest.fixture
async def sim(socket_enabled: None) -> AsyncIterator[SimServer]:
    server = make_sim()
    await server.start()
    yield server
    await server.stop()


@pytest.fixture
def entry(sim: SimServer) -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN,
        unique_id=MAC,
        title="Onkyo Test",
        data={CONF_HOST: "127.0.0.1", CONF_PORT: sim.port},
    )


async def setup(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


async def poll_state(hass: HomeAssistant, attribute: str | None, expected: object) -> None:
    """Wait until the main player's state (or one attribute) equals ``expected``."""
    async with asyncio.timeout(5):
        while True:
            state = hass.states.get("media_player.onkyo_tx_rz50")
            value = state.state if attribute is None else state.attributes.get(attribute)  # type: ignore[union-attr]
            if value == expected:
                return
            await asyncio.sleep(0.02)
