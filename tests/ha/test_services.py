"""The send_raw and survey actions."""

from __future__ import annotations

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.onkyo_eiscp.const import (
    ATTR_CONFIG_ENTRY_ID,
    ATTR_MESSAGE,
    DOMAIN,
    SERVICE_SEND_RAW,
    SERVICE_SURVEY,
)
from tests.ha.conftest import setup


async def test_send_raw_returns_replies(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    await setup(hass, entry)
    response = await hass.services.async_call(
        DOMAIN,
        SERVICE_SEND_RAW,
        {ATTR_CONFIG_ENTRY_ID: entry.entry_id, ATTR_MESSAGE: "!1PWRQSTN"},
        blocking=True,
        return_response=True,
    )
    assert set(response["replies"]) == {"PWR01"}


async def test_send_raw_without_prefix(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    await setup(hass, entry)
    response = await hass.services.async_call(
        DOMAIN,
        SERVICE_SEND_RAW,
        {ATTR_CONFIG_ENTRY_ID: entry.entry_id, ATTR_MESSAGE: "MVLQSTN"},
        blocking=True,
        return_response=True,
    )
    assert response["replies"][0].startswith("MVL")


async def test_unknown_entry_is_a_validation_error(
    hass: HomeAssistant, entry: MockConfigEntry
) -> None:
    await setup(hass, entry)
    with pytest.raises(ServiceValidationError) as raised:
        await hass.services.async_call(
            DOMAIN,
            SERVICE_SEND_RAW,
            {ATTR_CONFIG_ENTRY_ID: "nope", ATTR_MESSAGE: "PWRQSTN"},
            blocking=True,
            return_response=True,
        )
    assert raised.value.translation_key == "unknown_entry"


async def test_unloaded_entry_is_not_connected(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    await setup(hass, entry)
    await hass.config_entries.async_unload(entry.entry_id)
    with pytest.raises(HomeAssistantError) as raised:
        await hass.services.async_call(
            DOMAIN,
            SERVICE_SURVEY,
            {ATTR_CONFIG_ENTRY_ID: entry.entry_id},
            blocking=True,
            return_response=True,
        )
    assert raised.value.translation_key == "not_connected"


async def test_survey_is_a_sanitized_capture(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    await setup(hass, entry)
    response = await hass.services.async_call(
        DOMAIN,
        SERVICE_SURVEY,
        {ATTR_CONFIG_ENTRY_ID: entry.entry_id},
        blocking=True,
        return_response=True,
    )
    assert response["model"] == "TX-RZ50"
    assert set(response) == {"model", "firmware", "captured", "codes"}
    codes = response["codes"]
    assert codes["PWR"] == {
        "zone": "main",
        "states": {"on": "01"},
        "writes": [],
        "notes": "",
    }
    assert "NLT" not in codes
    assert "NCP" not in codes
    text = str(response).lower()
    assert "127.0.0.1" not in text
    assert "0009b0" not in text
