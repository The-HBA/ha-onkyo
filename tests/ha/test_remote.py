"""The remote entity against the simulated TX-RZ50."""

from __future__ import annotations

import pytest
from homeassistant.components.remote import (
    ATTR_COMMAND,
    ATTR_DELAY_SECS,
    ATTR_NUM_REPEATS,
    SERVICE_SEND_COMMAND,
)
from homeassistant.components.remote import DOMAIN as REMOTE
from homeassistant.const import (
    ATTR_ENTITY_ID,
    SERVICE_TURN_OFF,
    SERVICE_TURN_ON,
    STATE_OFF,
    STATE_ON,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from pytest_homeassistant_custom_component.common import MockConfigEntry

from tests.ha.conftest import setup
from tests.ha.entity_helpers import entity_id, wait_state


async def test_remote_follows_main_power(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    await setup(hass, entry)
    remote = entity_id(hass, REMOTE, "remote")
    assert hass.states.get(remote).state == STATE_ON  # type: ignore[union-attr]
    await hass.services.async_call(
        REMOTE, SERVICE_TURN_OFF, {ATTR_ENTITY_ID: remote}, blocking=True
    )
    await wait_state(hass, remote, STATE_OFF)
    await hass.services.async_call(REMOTE, SERVICE_TURN_ON, {ATTR_ENTITY_ID: remote}, blocking=True)
    await wait_state(hass, remote, STATE_ON, seconds=15)


async def test_send_command_sends_each_osd_key(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    await setup(hass, entry)
    remote = entity_id(hass, REMOTE, "remote")
    sent: list[tuple[str, str]] = []
    receiver = entry.runtime_data.receiver
    original = receiver.set

    async def spy(code: str, param: str) -> str:
        sent.append((code, param))
        return await original(code, param)

    receiver.set = spy  # type: ignore[method-assign]
    await hass.services.async_call(
        REMOTE,
        SERVICE_SEND_COMMAND,
        {
            ATTR_ENTITY_ID: remote,
            ATTR_COMMAND: ["menu", "Down"],
            ATTR_NUM_REPEATS: 2,
            ATTR_DELAY_SECS: 0,
        },
        blocking=True,
    )
    assert sent == [("OSD", "MENU"), ("OSD", "DOWN")] * 2
    await hass.services.async_call(
        REMOTE,
        SERVICE_SEND_COMMAND,
        {ATTR_ENTITY_ID: remote, ATTR_COMMAND: ["exit"]},
        blocking=True,
    )


async def test_unknown_key_is_rejected_before_anything_is_sent(
    hass: HomeAssistant, entry: MockConfigEntry
) -> None:
    await setup(hass, entry)
    remote = entity_id(hass, REMOTE, "remote")
    sent: list[str] = []
    receiver = entry.runtime_data.receiver
    original = receiver.set

    async def spy(code: str, param: str) -> str:
        sent.append(code + param)
        return await original(code, param)

    receiver.set = spy  # type: ignore[method-assign]
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            REMOTE,
            SERVICE_SEND_COMMAND,
            {ATTR_ENTITY_ID: remote, ATTR_COMMAND: ["menu", "banana"]},
            blocking=True,
        )
    assert sent == []
