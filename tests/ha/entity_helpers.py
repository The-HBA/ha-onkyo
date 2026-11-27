"""Helpers for the entity tests: find an entity by its unique ID, wait for a state."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from homeassistant.helpers import entity_registry as er

from tests.ha.conftest import MAC

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant


def entity_id(hass: HomeAssistant, domain: str, key: str, zone: str = "main") -> str:
    """Return the entity ID of ``<mac>-<zone>-<key>`` (fails when it does not exist)."""
    found = er.async_get(hass).async_get_entity_id(domain, "onkyo_eiscp", f"{MAC}-{zone}-{key}")
    assert found is not None, f"no {domain} entity {key}"
    return found


async def wait_state(hass: HomeAssistant, entity: str, expected: str, seconds: float = 5) -> None:
    """Wait until the entity's state equals ``expected``."""
    async with asyncio.timeout(seconds):
        while (state := hass.states.get(entity)) is None or state.state != expected:  # noqa: ASYNC110
            await asyncio.sleep(0.02)
