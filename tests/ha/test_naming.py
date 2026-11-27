"""Clean names, signal groups and error translation."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.onkyo_eiscp import naming
from custom_components.onkyo_eiscp.entity import translated_errors
from custom_components.onkyo_eiscp.lib import (
    ConnectionClosedError,
    NoReplyError,
    NotAvailableError,
)
from tests.ha.conftest import setup


def test_mode_name_prefers_rename_then_receiver_name_then_table() -> None:
    values = {"LMD": "80", "IFA": "HDMI 1,Dolby Atmos,48 kHz,5.1.2 ch,Dolby Atmos,7.1.4 ch"}
    assert naming.mode_name({}, values, "80") == "Dolby Atmos"
    assert naming.mode_name({}, values, "82") == "DTS Neural:X"
    renamed = {"listening_modes": {"80": {"name": "Atmos"}}}
    assert naming.mode_name(renamed, values, "80") == "Atmos"
    # A receiver name that is another code's table name never replaces this code's name.
    clash = {"LMD": "80", "IFA": "HDMI 1,PCM,48 kHz,2 ch,DTS Neural:X,7.1 ch"}
    assert naming.mode_name({}, clash, "80") == "Dolby Surround"
    assert naming.mode_name({}, {}, "ZZ") == "ZZ"


@pytest.mark.parametrize(
    ("ifa", "group"),
    [
        ("", naming.PCM),
        ("N/A", naming.PCM),
        ("HDMI 1,PCM,48 kHz,2 ch,Stereo,2 ch", naming.PCM),
        ("HDMI 1,Dolby Atmos/TrueHD,48 kHz,7.1 ch,Dolby Atmos,7.1.4 ch", naming.ATMOS),
        ("HDMI 1,DTS-HD MA,48 kHz,5.1 ch,DTS,5.1 ch", None),
    ],
)
def test_signal_group(ifa: str, group: str | None) -> None:
    assert naming.signal_group({"IFA": ifa} if ifa else {}) == group


async def test_mode_list_follows_signal_and_keeps_current(
    hass: HomeAssistant, entry: MockConfigEntry
) -> None:
    await setup(hass, entry)
    caps = entry.runtime_data.data.capabilities
    pcm = naming.mode_codes(caps, {}, {"LMD": "00"})
    atmos = naming.mode_codes(
        caps, {}, {"LMD": "80", "IFA": "HDMI 1,Dolby Atmos/TrueHD,48 kHz,7.1 ch,Dolby Atmos,7 ch"}
    )
    other = naming.mode_codes(
        caps, {}, {"LMD": "00", "IFA": "HDMI 1,DTS-HD MA,48 kHz,5.1 ch,DTS,5 ch"}
    )
    assert len(atmos) < len(pcm)
    assert other == list(caps.listening_modes) or set(other) >= set(caps.listening_modes) - {"00"}
    hidden = {"listening_modes": {"00": {"hidden": True}}}
    assert "00" in naming.mode_codes(caps, hidden, {"LMD": "00"})
    assert "00" not in naming.mode_codes(caps, hidden, {"LMD": "01"})


@pytest.mark.parametrize(
    ("error", "key"),
    [
        (NotAvailableError("MOT", "01"), "not_available"),
        (NoReplyError("LMD", "01"), "no_reply"),
        (ConnectionClosedError(), "not_connected"),
    ],
)
def test_errors_get_translation_keys(error: Exception, key: str) -> None:
    with pytest.raises(HomeAssistantError) as raised, translated_errors():
        raise error
    assert raised.value.translation_key == key


async def test_supported_growth_reloads_once(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    await setup(hass, entry)
    coordinator = entry.runtime_data
    coordinator._supported = frozenset({"PWR"})
    with patch.object(hass.config_entries, "async_schedule_reload") as reload:
        coordinator._on_change(frozenset({"PWR"}))
        coordinator._on_change(frozenset({"PWR"}))
    reload.assert_called_once_with(entry.entry_id)


async def test_smaller_supported_set_does_not_reload(
    hass: HomeAssistant, entry: MockConfigEntry
) -> None:
    await setup(hass, entry)
    coordinator = entry.runtime_data
    coordinator._supported = frozenset(coordinator.data.capabilities.supported | {"ZZZ"})
    with patch.object(hass.config_entries, "async_schedule_reload") as reload:
        coordinator._on_change(frozenset({"PWR"}))
    reload.assert_not_called()
