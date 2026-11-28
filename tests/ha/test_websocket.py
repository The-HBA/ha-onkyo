"""The card's websocket commands: card_info and set_names."""

from __future__ import annotations

from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.typing import WebSocketGenerator

from custom_components.onkyo_eiscp.const import (
    CONF_INPUT_ORDER,
    CONF_INPUTS,
    CONF_LISTENING_MODES,
    CONF_MAX_VOLUME,
    DOMAIN,
)
from tests.ha.conftest import MAC, setup

PLAYER = "media_player.onkyo_tx_rz50"


async def _ask(
    hass: HomeAssistant, hass_ws_client: WebSocketGenerator, message: dict[str, Any]
) -> dict[str, Any]:
    client = await hass_ws_client(hass)
    await client.send_json_auto_id(message)
    return await client.receive_json()


async def _info(
    hass: HomeAssistant, hass_ws_client: WebSocketGenerator, entry: MockConfigEntry
) -> dict[str, Any]:
    reply = await _ask(
        hass, hass_ws_client, {"type": "onkyo_eiscp/card_info", "entry_id": entry.entry_id}
    )
    assert reply["success"], reply
    return reply["result"]


def _source_list(hass: HomeAssistant) -> list[str]:
    state = hass.states.get(PLAYER)
    assert state is not None
    return list(state.attributes["source_list"])


async def test_card_info(
    hass: HomeAssistant, entry: MockConfigEntry, hass_ws_client: WebSocketGenerator
) -> None:
    await setup(hass, entry)
    info = await _info(hass, hass_ws_client, entry)
    device = dr.async_get(hass).async_get_device_by_identifier((DOMAIN, MAC), entry.entry_id)
    assert device is not None
    assert info["entry_id"] == entry.entry_id
    assert info["device_id"] == device.id
    assert info["model"] == "TX-RZ50"
    assert info["version"]
    assert info["zones"][0] == "main"
    assert info["volume_db_step"] == 0.5
    assert info["volume_max"] > 0
    assert set(info["dirac_slots"]) <= {"slot_1", "slot_2", "slot_3"}
    # The TX-RZ50 does not support the Home key (profile), so the card hides it.
    assert "home" not in info["remote_keys"]
    assert {"up", "enter", "exit", "menu", "quick", "audio", "video"} <= set(info["remote_keys"])
    groups = info["listening_mode_groups"]
    assert groups["00"] == "stereo"
    assert groups["80"] == "surround"
    assert set(groups.values()) <= {"stereo", "surround", "thx", "dsp", "other"}
    # No host and no MAC leave the integration.
    assert MAC not in str(info)
    assert "127.0.0.1" not in str(info)


async def test_card_info_lists_inputs_and_modes_for_the_edit_sheet(
    hass: HomeAssistant, entry: MockConfigEntry, hass_ws_client: WebSocketGenerator
) -> None:
    await setup(hass, entry)
    info = await _info(hass, hass_ws_client, entry)
    inputs = info["inputs"]
    assert [item["name"] for item in inputs if item["code"] == "11"] == ["Streaming"]
    assert all(item["custom"] == "" and item["hidden"] is False for item in inputs)
    assert {item["code"] for item in inputs} >= {"10", "11"}
    modes = {item["code"]: item for item in info["listening_modes"]}
    assert modes["00"]["name"] == "Stereo"
    assert modes["00"]["group"] == "stereo"
    assert "1F" not in modes


async def test_card_info_follows_the_options(
    hass: HomeAssistant, entry: MockConfigEntry, hass_ws_client: WebSocketGenerator
) -> None:
    entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        entry,
        options={
            CONF_MAX_VOLUME: 100,
            CONF_INPUTS: {"11": {"name": "Cast", "hidden": True}},
            CONF_INPUT_ORDER: ["11"],
        },
    )
    await setup(hass, entry)
    info = await _info(hass, hass_ws_client, entry)
    assert info["volume_max"] == 100
    assert info["inputs"][0] == {
        "code": "11",
        "name": "Streaming",
        "custom": "Cast",
        "hidden": True,
        "zones": info["inputs"][0]["zones"],
    }


async def test_card_info_by_device_id(
    hass: HomeAssistant, entry: MockConfigEntry, hass_ws_client: WebSocketGenerator
) -> None:
    await setup(hass, entry)
    device = dr.async_get(hass).async_get_device_by_identifier((DOMAIN, MAC), entry.entry_id)
    assert device is not None
    reply = await _ask(
        hass, hass_ws_client, {"type": "onkyo_eiscp/card_info", "device_id": device.id}
    )
    assert reply["success"]
    assert reply["result"]["entry_id"] == entry.entry_id


async def test_card_info_for_an_unknown_receiver(
    hass: HomeAssistant, entry: MockConfigEntry, hass_ws_client: WebSocketGenerator
) -> None:
    await setup(hass, entry)
    for target in ({"entry_id": "nope"}, {"device_id": "nope"}):
        reply = await _ask(hass, hass_ws_client, {"type": "onkyo_eiscp/card_info", **target})
        assert reply["success"] is False
        assert reply["error"]["code"] == "receiver_not_found"


async def test_card_info_needs_a_target(
    hass: HomeAssistant, entry: MockConfigEntry, hass_ws_client: WebSocketGenerator
) -> None:
    await setup(hass, entry)
    reply = await _ask(hass, hass_ws_client, {"type": "onkyo_eiscp/card_info"})
    assert reply["success"] is False
    assert reply["error"]["code"] == "invalid_format"


async def test_set_names_renames_hides_and_orders_inputs(
    hass: HomeAssistant, entry: MockConfigEntry, hass_ws_client: WebSocketGenerator
) -> None:
    await setup(hass, entry)
    before = await _info(hass, hass_ws_client, entry)
    codes = [item["code"] for item in before["inputs"]]
    first, last = codes[0], codes[-1]
    current = entry.runtime_data.data.values["SLI"]
    hide = next(code for code in codes if code not in {current, "11"})
    hidden_name = next(item["name"] for item in before["inputs"] if item["code"] == hide)
    reply = await _ask(
        hass,
        hass_ws_client,
        {
            "type": "onkyo_eiscp/set_names",
            "entry_id": entry.entry_id,
            "kind": "inputs",
            "names": {
                "11": {"name": "  Cast  ", "hidden": False},
                hide: {"name": "", "hidden": True},
            },
            "order": [last, first],
        },
    )
    assert reply["success"], reply
    await hass.async_block_till_done()
    assert entry.options[CONF_INPUTS] == {
        "11": {"name": "Cast", "hidden": False},
        hide: {"name": "", "hidden": True},
    }
    assert entry.options[CONF_INPUT_ORDER] == [last, first]
    names = _source_list(hass)
    assert "Cast" in names
    assert hidden_name not in names
    after = await _info(hass, hass_ws_client, entry)
    assert [item["code"] for item in after["inputs"]][:2] == [last, first]
    by_code = {item["code"]: item for item in after["inputs"]}
    assert by_code["11"]["custom"] == "Cast"
    assert by_code[hide]["hidden"] is True


async def test_set_names_empty_means_the_receivers_name(
    hass: HomeAssistant, entry: MockConfigEntry, hass_ws_client: WebSocketGenerator
) -> None:
    entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        entry, options={CONF_INPUTS: {"11": {"name": "Cast", "hidden": False}}}
    )
    await setup(hass, entry)
    reply = await _ask(
        hass,
        hass_ws_client,
        {
            "type": "onkyo_eiscp/set_names",
            "entry_id": entry.entry_id,
            "kind": "inputs",
            "names": {"11": {"name": "Streaming", "hidden": False}},
        },
    )
    assert reply["success"], reply
    assert entry.options[CONF_INPUTS] == {}
    assert "Streaming" in _source_list(hass)


async def test_the_receivers_own_order_is_stored_as_no_order(
    hass: HomeAssistant, entry: MockConfigEntry, hass_ws_client: WebSocketGenerator
) -> None:
    entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(entry, options={CONF_INPUT_ORDER: ["11"]})
    await setup(hass, entry)
    info = await _info(hass, hass_ws_client, entry)
    reply = await _ask(
        hass,
        hass_ws_client,
        {
            "type": "onkyo_eiscp/set_names",
            "entry_id": entry.entry_id,
            "kind": "inputs",
            "names": {},
            "order": [item["code"] for item in info["inputs"]][::-1],
        },
    )
    assert reply["success"], reply
    assert CONF_INPUT_ORDER in entry.options
    receiver_order = [item.code for item in entry.runtime_data.data.capabilities.inputs]
    reply = await _ask(
        hass,
        hass_ws_client,
        {
            "type": "onkyo_eiscp/set_names",
            "entry_id": entry.entry_id,
            "kind": "inputs",
            "names": {},
            "order": receiver_order,
        },
    )
    assert reply["success"], reply
    assert CONF_INPUT_ORDER not in entry.options


async def test_set_names_renames_and_hides_listening_modes(
    hass: HomeAssistant, entry: MockConfigEntry, hass_ws_client: WebSocketGenerator
) -> None:
    await setup(hass, entry)
    reply = await _ask(
        hass,
        hass_ws_client,
        {
            "type": "onkyo_eiscp/set_names",
            "entry_id": entry.entry_id,
            "kind": "modes",
            "names": {"00": {"name": "Plain stereo"}, "08": {"hidden": True}},
        },
    )
    assert reply["success"], reply
    await hass.async_block_till_done()
    assert entry.options[CONF_LISTENING_MODES]["00"] == {"name": "Plain stereo", "hidden": False}
    assert entry.options[CONF_LISTENING_MODES]["08"] == {"name": "", "hidden": True}
    state = hass.states.get(PLAYER)
    assert state is not None
    assert "Orchestra" not in state.attributes["sound_mode_list"]


async def test_a_name_in_use_is_refused_and_nothing_is_stored(
    hass: HomeAssistant, entry: MockConfigEntry, hass_ws_client: WebSocketGenerator
) -> None:
    await setup(hass, entry)
    reply = await _ask(
        hass,
        hass_ws_client,
        {
            "type": "onkyo_eiscp/set_names",
            "entry_id": entry.entry_id,
            "kind": "inputs",
            "names": {"11": {"name": "movie"}},
        },
    )
    assert reply["success"] is False
    assert reply["error"]["code"] == "name_in_use"
    assert not entry.options.get(CONF_INPUTS)


async def test_unknown_codes_are_refused(
    hass: HomeAssistant, entry: MockConfigEntry, hass_ws_client: WebSocketGenerator
) -> None:
    await setup(hass, entry)
    for message in (
        {"kind": "inputs", "names": {"ZZ": {"name": "x"}}},
        {"kind": "modes", "names": {"ZZ": {"name": "x"}}},
        {"kind": "inputs", "names": {}, "order": ["ZZ"]},
    ):
        reply = await _ask(
            hass,
            hass_ws_client,
            {"type": "onkyo_eiscp/set_names", "entry_id": entry.entry_id, **message},
        )
        assert reply["success"] is False
        assert reply["error"]["code"] == "invalid_names"


async def test_set_names_needs_an_administrator(
    hass: HomeAssistant,
    entry: MockConfigEntry,
    hass_ws_client: WebSocketGenerator,
    hass_read_only_access_token: str,
) -> None:
    await setup(hass, entry)
    client = await hass_ws_client(hass, hass_read_only_access_token)
    await client.send_json_auto_id(
        {
            "type": "onkyo_eiscp/set_names",
            "entry_id": entry.entry_id,
            "kind": "inputs",
            "names": {"11": {"name": "Cast"}},
        }
    )
    reply = await client.receive_json()
    assert reply["success"] is False
    assert reply["error"]["code"] == "unauthorized"
    assert not entry.options.get(CONF_INPUTS)
    # Reading is open to every logged-in user.
    await client.send_json_auto_id({"type": "onkyo_eiscp/card_info", "entry_id": entry.entry_id})
    assert (await client.receive_json())["success"]


async def test_a_name_too_long_for_the_buttons_is_refused(
    hass: HomeAssistant, entry: MockConfigEntry, hass_ws_client: WebSocketGenerator
) -> None:
    await setup(hass, entry)
    reply = await _ask(
        hass,
        hass_ws_client,
        {
            "type": "onkyo_eiscp/set_names",
            "entry_id": entry.entry_id,
            "kind": "inputs",
            "names": {"11": {"name": "x" * 33}},
        },
    )
    assert reply["success"] is False
    assert reply["error"]["code"] == "invalid_names"
