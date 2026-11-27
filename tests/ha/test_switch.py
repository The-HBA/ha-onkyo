"""The switches against the simulated TX-RZ50."""

from __future__ import annotations

import pytest
from homeassistant.components.media_player import ATTR_SOUND_MODE, SERVICE_SELECT_SOUND_MODE
from homeassistant.components.media_player import DOMAIN as MEDIA_PLAYER
from homeassistant.components.switch import DOMAIN as SWITCH
from homeassistant.const import (
    ATTR_ENTITY_ID,
    SERVICE_TURN_OFF,
    SERVICE_TURN_ON,
    STATE_OFF,
    STATE_ON,
    STATE_UNAVAILABLE,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from pytest_homeassistant_custom_component.common import MockConfigEntry

from tests.ha.conftest import setup
from tests.ha.entity_helpers import entity_id, wait_state

PLAYER = "media_player.onkyo_tx_rz50"


async def call(hass: HomeAssistant, service: str, entity: str) -> None:
    await hass.services.async_call(SWITCH, service, {ATTR_ENTITY_ID: entity}, blocking=True)


async def test_cinema_filter_switches(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    await setup(hass, entry)
    entity = entity_id(hass, SWITCH, "cinema_filter")
    assert hass.states.get(entity).state == STATE_OFF  # type: ignore[union-attr]
    await call(hass, SERVICE_TURN_ON, entity)
    await wait_state(hass, entity, STATE_ON)
    await call(hass, SERVICE_TURN_OFF, entity)
    await wait_state(hass, entity, STATE_OFF)


async def test_music_optimizer_only_in_stereo(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    await setup(hass, entry)
    entity = entity_id(hass, SWITCH, "music_optimizer")
    # The simulated receiver starts in DTS Neural:X, where MOT is refused.
    with pytest.raises(HomeAssistantError):
        await call(hass, SERVICE_TURN_ON, entity)
    await wait_state(hass, entity, STATE_UNAVAILABLE)
    await hass.services.async_call(
        MEDIA_PLAYER,
        SERVICE_SELECT_SOUND_MODE,
        {ATTR_ENTITY_ID: PLAYER, ATTR_SOUND_MODE: "Stereo"},
        blocking=True,
    )
    await wait_state(hass, entity, STATE_OFF)
    await call(hass, SERVICE_TURN_ON, entity)
    await wait_state(hass, entity, STATE_ON)
    await call(hass, SERVICE_TURN_OFF, entity)
    await wait_state(hass, entity, STATE_OFF)


async def test_switches_follow_power(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    await setup(hass, entry)
    entity = entity_id(hass, SWITCH, "cinema_filter")
    await hass.services.async_call(
        MEDIA_PLAYER, "turn_off", {ATTR_ENTITY_ID: PLAYER}, blocking=True
    )
    await wait_state(hass, entity, STATE_UNAVAILABLE)


async def test_music_optimizer_refusal_is_remembered_per_mode(
    hass: HomeAssistant, entry: MockConfigEntry
) -> None:
    await setup(hass, entry)
    entity = entity_id(hass, SWITCH, "music_optimizer")
    with pytest.raises(HomeAssistantError):
        await call(hass, SERVICE_TURN_ON, entity)
    await wait_state(hass, entity, STATE_UNAVAILABLE)
    for mode in ("Stereo", "DTS Neural:X"):
        await hass.services.async_call(
            MEDIA_PLAYER,
            SERVICE_SELECT_SOUND_MODE,
            {ATTR_ENTITY_ID: PLAYER, ATTR_SOUND_MODE: mode},
            blocking=True,
        )
        await wait_state(hass, entity, STATE_OFF if mode == "Stereo" else STATE_UNAVAILABLE)
