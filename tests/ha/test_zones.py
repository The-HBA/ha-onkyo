"""Zone 2 and zone 3 players against the simulated TX-RZ50."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.components.media_player import (
    ATTR_INPUT_SOURCE,
    ATTR_MEDIA_VOLUME_LEVEL,
    ATTR_MEDIA_VOLUME_MUTED,
    SERVICE_SELECT_SOURCE,
    MediaPlayerEntityFeature,
)
from homeassistant.components.media_player import DOMAIN as MEDIA_PLAYER
from homeassistant.const import (
    ATTR_ENTITY_ID,
    ATTR_SUPPORTED_FEATURES,
    SERVICE_TURN_OFF,
    SERVICE_TURN_ON,
    SERVICE_VOLUME_DOWN,
    SERVICE_VOLUME_MUTE,
    SERVICE_VOLUME_SET,
    SERVICE_VOLUME_UP,
    STATE_OFF,
    STATE_ON,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from pytest_homeassistant_custom_component.common import MockConfigEntry

from tests.ha.conftest import setup
from tests.ha.entity_helpers import entity_id, wait_state

ZONE2 = "media_player.onkyo_tx_rz50_zone_2"
ZONE3 = "media_player.onkyo_tx_rz50_zone_3"


async def test_zones_exist_with_unique_ids(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    await setup(hass, entry)
    assert entity_id(hass, MEDIA_PLAYER, "zone2", "zone2") == ZONE2
    assert entity_id(hass, MEDIA_PLAYER, "zone3", "zone3") == ZONE3
    assert hass.states.get(ZONE2).state == STATE_OFF  # type: ignore[union-attr]
    assert hass.states.get(ZONE3).state == STATE_OFF  # type: ignore[union-attr]


async def test_zone_sources_follow_the_zone_mask(
    hass: HomeAssistant, entry: MockConfigEntry
) -> None:
    await setup(hass, entry)
    zone_sources = hass.states.get(ZONE2).attributes["source_list"]  # type: ignore[union-attr]
    main_sources = hass.states.get("media_player.onkyo_tx_rz50").attributes["source_list"]  # type: ignore[union-attr]
    assert "Source" in zone_sources
    assert "Source" not in main_sources
    assert len(zone_sources) == len(set(zone_sources))
    # The codes run parallel to the names, so the card finds "follow the main zone" by code 80.
    attrs = hass.states.get(ZONE2).attributes  # type: ignore[union-attr]
    assert len(attrs["source_codes"]) == len(zone_sources)
    assert attrs["source_codes"][zone_sources.index("Source")] == "80"
    assert set(zone_sources[:-1]) <= set(main_sources)


def _zvl_not_available(entry: MockConfigEntry) -> None:
    """Make ZVL answer N/A, as the TX-RZ50 does while zone 2 is on (the simulator holds a value)."""
    coordinator = entry.runtime_data
    coordinator.receiver._values.pop("ZVL", None)
    coordinator.async_set_updated_data(coordinator._snapshot(frozenset({"ZVL"})))


async def test_zone2_on_has_no_volume_while_zvl_is_na(
    hass: HomeAssistant, entry: MockConfigEntry
) -> None:
    await setup(hass, entry)
    await hass.services.async_call(
        MEDIA_PLAYER, SERVICE_TURN_ON, {ATTR_ENTITY_ID: ZONE2}, blocking=True
    )
    await wait_state(hass, ZONE2, STATE_ON)
    _zvl_not_available(entry)
    await hass.async_block_till_done()
    features = hass.states.get(ZONE2).attributes[ATTR_SUPPORTED_FEATURES]  # type: ignore[union-attr]
    assert not features & MediaPlayerEntityFeature.VOLUME_SET
    assert not features & MediaPlayerEntityFeature.VOLUME_STEP
    assert features & MediaPlayerEntityFeature.SELECT_SOURCE
    assert hass.states.get(ZONE2).attributes.get("volume_level") is None  # type: ignore[union-attr]
    await hass.services.async_call(
        MEDIA_PLAYER, SERVICE_TURN_OFF, {ATTR_ENTITY_ID: ZONE2}, blocking=True
    )
    await wait_state(hass, ZONE2, STATE_OFF)


async def test_zone2_source_and_mute(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    await setup(hass, entry)
    await hass.services.async_call(
        MEDIA_PLAYER, SERVICE_TURN_ON, {ATTR_ENTITY_ID: ZONE2}, blocking=True
    )
    await wait_state(hass, ZONE2, STATE_ON)
    await hass.services.async_call(
        MEDIA_PLAYER,
        SERVICE_SELECT_SOURCE,
        {ATTR_ENTITY_ID: ZONE2, ATTR_INPUT_SOURCE: "Movie"},
        blocking=True,
    )
    await hass.services.async_call(
        MEDIA_PLAYER,
        SERVICE_VOLUME_MUTE,
        {ATTR_ENTITY_ID: ZONE2, ATTR_MEDIA_VOLUME_MUTED: True},
        blocking=True,
    )
    await hass.async_block_till_done()
    attributes = hass.states.get(ZONE2).attributes  # type: ignore[union-attr]
    assert attributes["source"] == "Movie"
    assert attributes["is_volume_muted"] is True
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            MEDIA_PLAYER,
            SERVICE_SELECT_SOURCE,
            {ATTR_ENTITY_ID: ZONE2, ATTR_INPUT_SOURCE: "Nope"},
            blocking=True,
        )


async def test_zone3_power_on_is_refused(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    await setup(hass, entry)
    with pytest.raises(HomeAssistantError) as raised:
        await hass.services.async_call(
            MEDIA_PLAYER, SERVICE_TURN_ON, {ATTR_ENTITY_ID: ZONE3}, blocking=True
        )
    assert raised.value.translation_key == "zone_power_refused"
    assert hass.states.get(ZONE3).state == STATE_OFF  # type: ignore[union-attr]


async def test_zone_volume_when_zvl_holds_a_value(
    hass: HomeAssistant, entry: MockConfigEntry
) -> None:
    await setup(hass, entry)
    await hass.services.async_call(
        MEDIA_PLAYER, SERVICE_TURN_ON, {ATTR_ENTITY_ID: ZONE2}, blocking=True
    )
    await wait_state(hass, ZONE2, STATE_ON)
    state = hass.states.get(ZONE2)
    assert state is not None
    assert state.attributes[ATTR_SUPPORTED_FEATURES] & MediaPlayerEntityFeature.VOLUME_SET
    assert state.attributes["volume_level"] == pytest.approx(0x50 / 200)
    assert state.attributes["volume_db"] == 0x50 / 2 - 82
    receiver = entry.runtime_data.receiver
    with patch.object(receiver, "set", AsyncMock(return_value="")) as sent:
        for service, data, param in (
            (SERVICE_VOLUME_SET, {ATTR_MEDIA_VOLUME_LEVEL: 0.2}, "28"),
            (SERVICE_VOLUME_UP, {}, "52"),
            (SERVICE_VOLUME_DOWN, {}, "4E"),
        ):
            await hass.services.async_call(
                MEDIA_PLAYER, service, {ATTR_ENTITY_ID: ZONE2, **data}, blocking=True
            )
            sent.assert_called_with("ZVL", param)


async def test_zone_volume_goes_away_when_the_receiver_refuses_it(
    hass: HomeAssistant, entry: MockConfigEntry
) -> None:
    """The simulator answers N/A to ZVL while zone 2 is on, as the TX-RZ50 does."""
    await setup(hass, entry)
    await hass.services.async_call(
        MEDIA_PLAYER, SERVICE_TURN_ON, {ATTR_ENTITY_ID: ZONE2}, blocking=True
    )
    await wait_state(hass, ZONE2, STATE_ON)
    with pytest.raises(HomeAssistantError) as raised:
        await hass.services.async_call(
            MEDIA_PLAYER,
            SERVICE_VOLUME_SET,
            {ATTR_ENTITY_ID: ZONE2, ATTR_MEDIA_VOLUME_LEVEL: 0.3},
            blocking=True,
        )
    assert raised.value.translation_key == "not_available"
    await hass.async_block_till_done()
    attributes = hass.states.get(ZONE2).attributes  # type: ignore[union-attr]
    assert not attributes[ATTR_SUPPORTED_FEATURES] & MediaPlayerEntityFeature.VOLUME_SET
    assert "volume_level" not in attributes
