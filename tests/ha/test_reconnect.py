"""The entities follow a lost and restored connection."""

from __future__ import annotations

from homeassistant.components.number import DOMAIN as NUMBER
from homeassistant.components.select import DOMAIN as SELECT
from homeassistant.components.sensor import DOMAIN as SENSOR
from homeassistant.components.switch import DOMAIN as SWITCH
from homeassistant.const import STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from tests.ha.conftest import setup
from tests.ha.entity_helpers import entity_id, wait_state
from tests.lib.lib_helpers import poll
from tools.eiscp_sim import SimServer

KEYS = (
    (SELECT, "dirac_slot", "slot_3"),
    (NUMBER, "bass", "0.0"),
    (SWITCH, "cinema_filter", "off"),
    (SENSOR, "audio_input", "PCM 44.1 kHz"),
)


async def test_entities_go_unavailable_and_come_back(
    hass: HomeAssistant, entry: MockConfigEntry, sim: SimServer
) -> None:
    await setup(hass, entry)
    for domain, key, expected in KEYS:
        assert hass.states.get(entity_id(hass, domain, key)).state == expected  # type: ignore[union-attr]
    for writer in list(sim._connections):
        sim._drop(writer)
    for domain, key, _ in KEYS:
        await wait_state(hass, entity_id(hass, domain, key), STATE_UNAVAILABLE)
    for domain, key, expected in KEYS:
        await wait_state(hass, entity_id(hass, domain, key), expected, seconds=10)
    await poll(lambda: sim.connection_count == 1)
