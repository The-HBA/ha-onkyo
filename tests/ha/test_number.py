"""The number entities against the simulated TX-RZ50."""

from __future__ import annotations

import pytest
from homeassistant.components.media_player import ATTR_SOUND_MODE, SERVICE_SELECT_SOUND_MODE
from homeassistant.components.media_player import DOMAIN as MEDIA_PLAYER
from homeassistant.components.number import ATTR_VALUE, SERVICE_SET_VALUE
from homeassistant.components.number import DOMAIN as NUMBER
from homeassistant.const import ATTR_ENTITY_ID, STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from tests.ha.conftest import setup
from tests.ha.entity_helpers import entity_id, wait_state

PLAYER = "media_player.onkyo_tx_rz50"


async def set_value(hass: HomeAssistant, entity: str, value: float) -> None:
    await hass.services.async_call(
        NUMBER, SERVICE_SET_VALUE, {ATTR_ENTITY_ID: entity, ATTR_VALUE: value}, blocking=True
    )


async def test_ranges_come_from_the_command_table(
    hass: HomeAssistant, entry: MockConfigEntry
) -> None:
    await setup(hass, entry)
    bass = hass.states.get(entity_id(hass, NUMBER, "bass"))
    assert bass is not None
    assert (bass.attributes["min"], bass.attributes["max"], bass.attributes["step"]) == (-10, 10, 1)
    sub = hass.states.get(entity_id(hass, NUMBER, "subwoofer_level"))
    assert sub is not None
    assert (sub.attributes["min"], sub.attributes["max"], sub.attributes["step"]) == (-15, 12, 0.5)
    assert sub.attributes["unit_of_measurement"] == "dB"
    sleep = hass.states.get(entity_id(hass, NUMBER, "sleep_timer"))
    assert sleep is not None
    assert sleep.attributes["max"] == 90
    assert sleep.attributes["unit_of_measurement"] == "min"
    assert hass.states.get(entity_id(hass, NUMBER, "av_sync")).attributes["max"] == 500  # type: ignore[union-attr]


async def test_bass_and_treble_write_one_side(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    await setup(hass, entry)
    bass = entity_id(hass, NUMBER, "bass")
    treble = entity_id(hass, NUMBER, "treble")
    await set_value(hass, bass, 3)
    await wait_state(hass, bass, "3.0")
    assert hass.states.get(treble).state == "0.0"  # type: ignore[union-attr]
    await set_value(hass, treble, -2)
    await wait_state(hass, treble, "-2.0")
    assert hass.states.get(bass).state == "3.0"  # type: ignore[union-attr]
    await set_value(hass, bass, 0)
    await set_value(hass, treble, 0)
    await wait_state(hass, bass, "0.0")
    await wait_state(hass, treble, "0.0")


async def test_subwoofer_level_takes_half_steps(
    hass: HomeAssistant, entry: MockConfigEntry
) -> None:
    await setup(hass, entry)
    sub = entity_id(hass, NUMBER, "subwoofer_level")
    assert hass.states.get(sub).state == "-5.0"  # type: ignore[union-attr]
    await set_value(hass, sub, -4.5)
    await wait_state(hass, sub, "-4.5")
    await set_value(hass, sub, -5)
    await wait_state(hass, sub, "-5.0")


async def test_sleep_timer_and_av_sync(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    await setup(hass, entry)
    sleep = entity_id(hass, NUMBER, "sleep_timer")
    await set_value(hass, sleep, 30)
    await wait_state(hass, sleep, "30.0")
    await set_value(hass, sleep, 0)
    await wait_state(hass, sleep, "0.0")
    sync = entity_id(hass, NUMBER, "av_sync")
    await set_value(hass, sync, 20)
    await wait_state(hass, sync, "20.0")
    await set_value(hass, sync, 0)
    await wait_state(hass, sync, "0.0")


async def test_subwoofer_2_is_disabled_by_default(
    hass: HomeAssistant, entry: MockConfigEntry
) -> None:
    await setup(hass, entry)
    entity = entity_id(hass, NUMBER, "subwoofer2_level")
    registry_entry = er.async_get(hass).async_get(entity)
    assert registry_entry is not None
    assert registry_entry.disabled_by is er.RegistryEntryDisabler.INTEGRATION
    assert hass.states.get(entity) is None


@pytest.mark.parametrize("key", ["center_level", "dialog_level"])
async def test_refused_levels_become_unavailable(
    hass: HomeAssistant, entry: MockConfigEntry, key: str
) -> None:
    await setup(hass, entry)
    entity = entity_id(hass, NUMBER, key)
    assert hass.states.get(entity).state != STATE_UNAVAILABLE  # type: ignore[union-attr]
    with pytest.raises(HomeAssistantError):
        await set_value(hass, entity, 1)
    await wait_state(hass, entity, STATE_UNAVAILABLE)


async def test_vocal_enhancer_not_in_all_ch_stereo(
    hass: HomeAssistant, entry: MockConfigEntry
) -> None:
    await setup(hass, entry)
    voc = entity_id(hass, NUMBER, "vocal_enhancer")
    assert hass.states.get(voc).state != STATE_UNAVAILABLE  # type: ignore[union-attr]
    await hass.services.async_call(
        MEDIA_PLAYER,
        SERVICE_SELECT_SOUND_MODE,
        {ATTR_ENTITY_ID: PLAYER, ATTR_SOUND_MODE: "All Ch Stereo"},
        blocking=True,
    )
    await hass.async_block_till_done()
    # The simulator answers the read, but refuses the set; the refusal makes it unavailable here.
    with pytest.raises(HomeAssistantError):
        await set_value(hass, voc, 1)
    await wait_state(hass, voc, STATE_UNAVAILABLE)
    await hass.services.async_call(
        MEDIA_PLAYER,
        SERVICE_SELECT_SOUND_MODE,
        {ATTR_ENTITY_ID: PLAYER, ATTR_SOUND_MODE: "Stereo"},
        blocking=True,
    )
    await wait_state(hass, voc, "0.0")


async def test_numbers_are_unavailable_in_standby(
    hass: HomeAssistant, entry: MockConfigEntry
) -> None:
    await setup(hass, entry)
    bass = entity_id(hass, NUMBER, "bass")
    await hass.services.async_call(
        MEDIA_PLAYER, "turn_off", {ATTR_ENTITY_ID: PLAYER}, blocking=True
    )
    await wait_state(hass, bass, STATE_UNAVAILABLE)


async def test_av_sync_is_snapped_to_its_step(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    await setup(hass, entry)
    sync = entity_id(hass, NUMBER, "av_sync")
    await set_value(hass, sync, 7)  # not a multiple of 5 ms
    await wait_state(hass, sync, "5.0")
    await set_value(hass, sync, 0)
    await wait_state(hass, sync, "0.0")


async def test_entities_do_not_write_state_for_other_codes(
    hass: HomeAssistant, entry: MockConfigEntry
) -> None:
    await setup(hass, entry)
    bass = entity_id(hass, NUMBER, "bass")
    before = hass.states.get(bass).last_updated  # type: ignore[union-attr]
    volume = 0.4
    await hass.services.async_call(
        MEDIA_PLAYER,
        "volume_set",
        {ATTR_ENTITY_ID: PLAYER, "volume_level": volume},
        blocking=True,
    )
    await hass.async_block_till_done()
    assert hass.states.get(PLAYER).attributes["volume_level"] == pytest.approx(volume, abs=0.02)  # type: ignore[union-attr]
    assert hass.states.get(bass).last_updated == before  # type: ignore[union-attr]
