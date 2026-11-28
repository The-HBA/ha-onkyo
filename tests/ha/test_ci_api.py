"""The CI settings websocket commands: info, read, set and restore (simulator-backed)."""

from __future__ import annotations

from typing import Any

import pytest
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.typing import WebSocketGenerator

from tests.ha.conftest import setup


async def _ask(
    hass: HomeAssistant,
    hass_ws_client: WebSocketGenerator,
    entry: MockConfigEntry,
    command: str,
    token: str | None = None,
    **fields: Any,
) -> dict[str, Any]:
    client = await hass_ws_client(hass, token) if token else await hass_ws_client(hass)
    await client.send_json_auto_id(
        {"type": f"onkyo_eiscp/{command}", "entry_id": entry.entry_id, **fields}
    )
    return await client.receive_json()


async def test_info_lists_the_families_and_hides_status_ones(
    hass: HomeAssistant, entry: MockConfigEntry, hass_ws_client: WebSocketGenerator
) -> None:
    await setup(hass, entry)
    reply = await _ask(hass, hass_ws_client, entry, "ci_info")
    assert reply["success"], reply
    assert reply["result"]["supported"] is True
    families = {item["code"]: item for item in reply["result"]["families"]}
    assert {"LCC", "SDC", "COC", "EQC", "AKC", "CFC", "NTC", "N2C"} <= set(families)
    assert not {"MNC", "ST-", "AM-"} & set(families)
    assert families["LCC"]["calibration"] is True
    assert families["CFC"]["writable"] is False
    assert families["CFC"]["reason"]
    assert families["NTC"]["writable"] is False
    # Field flags: the library's read-only fields stay read-only.
    assert families["SDC"]["fields"]["UN"]["writable"] is False
    assert families["SDC"]["fields"]["FL"]["writable"] is True
    assert families["COC"]["fields"]["DB"]["writable"] is False
    assert "MM" not in families["LCC"]["fields"]
    # The TX-RZ50 has zones 2 and 3.
    assert [key["ZN"] for key in families["MZC"]["keys"]] == ["002", "003"]


async def test_read_one_record_and_a_whole_family(
    hass: HomeAssistant, entry: MockConfigEntry, hass_ws_client: WebSocketGenerator
) -> None:
    await setup(hass, entry)
    one = await _ask(hass, hass_ws_client, entry, "ci_read", code="LCC", key={"MM": "MM3"})
    assert one["success"], one
    [record] = one["result"]["records"]
    assert record["key"] == {"MM": "MM3"}
    assert record["fields"]["SW"] == "-10"
    assert record["restorable"] == []
    every = await _ask(hass, hass_ws_client, entry, "ci_read", code="EQC")
    assert len(every["result"]["records"]) == 21
    names = await _ask(hass, hass_ws_client, entry, "ci_read", code="NMC")
    assert {item["key"]["SL"] for item in names["result"]["records"]} >= {"BD", "TV", "PHO"}


async def test_read_refuses_status_and_unknown_families(
    hass: HomeAssistant, entry: MockConfigEntry, hass_ws_client: WebSocketGenerator
) -> None:
    await setup(hass, entry)
    for code in ("MNC", "ZZZ"):
        reply = await _ask(hass, hass_ws_client, entry, "ci_read", code=code)
        assert reply["success"] is False
        assert reply["error"]["code"] == "ci_unknown_family"


async def test_a_silent_key_is_an_error_for_one_record_and_skipped_for_a_family(
    hass: HomeAssistant, entry: MockConfigEntry, hass_ws_client: WebSocketGenerator
) -> None:
    await setup(hass, entry)
    reply = await _ask(hass, hass_ws_client, entry, "ci_read", code="NMC", key={"SL": "NET"})
    assert reply["success"] is False
    assert reply["error"]["code"] == "ci_no_reply"


async def test_set_changes_a_field_and_reads_it_back(
    hass: HomeAssistant, entry: MockConfigEntry, hass_ws_client: WebSocketGenerator
) -> None:
    await setup(hass, entry)
    reply = await _ask(hass, hass_ws_client, entry, "ci_set", code="HDC", changes={"CE": "000"})
    assert reply["success"], reply
    assert reply["result"]["fields"]["CE"] == "000"
    assert reply["result"]["restorable"] == []  # not a calibration family
    again = await _ask(hass, hass_ws_client, entry, "ci_read", code="HDC", key={})
    assert again["result"]["records"][0]["fields"]["CE"] == "000"


async def test_a_calibration_set_can_be_restored(
    hass: HomeAssistant, entry: MockConfigEntry, hass_ws_client: WebSocketGenerator
) -> None:
    await setup(hass, entry)
    key = {"MM": "MM1"}
    first = await _ask(
        hass, hass_ws_client, entry, "ci_set", code="LCC", key=key, changes={"SW": "-29"}
    )
    assert first["success"], first
    second = await _ask(
        hass,
        hass_ws_client,
        entry,
        "ci_set",
        code="LCC",
        key=key,
        changes={"SW": "-28", "FL": "+08"},
    )
    assert second["result"]["fields"]["SW"] == "-28"
    assert sorted(second["result"]["restorable"]) == ["FL", "SW"]
    done = await _ask(hass, hass_ws_client, entry, "ci_restore", code="LCC", key=key)
    assert done["success"], done
    # The very first old values are back, not the ones before the second step.
    assert done["result"]["fields"]["SW"] == "-30"
    assert done["result"]["fields"]["FL"] == "+07"
    assert done["result"]["restorable"] == []
    nothing = await _ask(hass, hass_ws_client, entry, "ci_restore", code="LCC", key=key)
    assert nothing["error"]["code"] == "ci_nothing_to_restore"


async def test_keep_forgets_the_saved_values_without_writing(
    hass: HomeAssistant, entry: MockConfigEntry, hass_ws_client: WebSocketGenerator
) -> None:
    await setup(hass, entry)
    key = {"MM": "MM2"}
    await _ask(hass, hass_ws_client, entry, "ci_set", code="SDC", key=key, changes={"FR": "004"})
    kept = await _ask(hass, hass_ws_client, entry, "ci_restore", code="SDC", key=key, keep=True)
    assert kept["success"], kept
    read = await _ask(hass, hass_ws_client, entry, "ci_read", code="SDC", key=key)
    [record] = read["result"]["records"]
    assert record["fields"]["FR"] == "004"
    assert record["restorable"] == []


@pytest.mark.parametrize(
    ("code", "key", "changes"),
    [
        ("CFC", None, {"IM": "004"}),
        ("NTC", None, {"IP": "00000000"}),
        ("N2C", None, {"FN": "x"}),
        ("SDC", {"MM": "MM1"}, {"UN": "FTS"}),
        ("COC", {"MM": "MM1", "XM": "IND"}, {"DB": "000"}),
        ("APC", None, {"NS": "000"}),
    ],
)
async def test_read_only_families_and_fields_are_refused(  # noqa: PLR0913, PLR0917
    hass: HomeAssistant,
    entry: MockConfigEntry,
    hass_ws_client: WebSocketGenerator,
    code: str,
    key: dict[str, str] | None,
    changes: dict[str, str],
) -> None:
    await setup(hass, entry)
    extra = {"key": key} if key else {}
    reply = await _ask(hass, hass_ws_client, entry, "ci_set", code=code, changes=changes, **extra)
    assert reply["success"] is False
    assert reply["error"]["code"] == "ci_refused"


async def test_a_bad_value_is_invalid_and_an_ignored_set_is_reported(
    hass: HomeAssistant, entry: MockConfigEntry, hass_ws_client: WebSocketGenerator
) -> None:
    await setup(hass, entry)
    bad = await _ask(hass, hass_ws_client, entry, "ci_set", code="HDC", changes={"CE": "7"})
    assert bad["error"]["code"] == "ci_invalid"
    # The simulator, like the TX-RZ50, ignores VIC sets.
    ignored = await _ask(hass, hass_ws_client, entry, "ci_set", code="VIC", changes={"CD": "CV1"})
    assert ignored["error"]["code"] == "ci_not_applied"


async def test_changes_need_an_administrator_and_reads_do_not(
    hass: HomeAssistant,
    entry: MockConfigEntry,
    hass_ws_client: WebSocketGenerator,
    hass_read_only_access_token: str,
) -> None:
    await setup(hass, entry)
    for command, fields in (
        ("ci_set", {"code": "HDC", "changes": {"CE": "000"}}),
        ("ci_restore", {"code": "LCC", "key": {"MM": "MM1"}}),
    ):
        reply = await _ask(
            hass, hass_ws_client, entry, command, hass_read_only_access_token, **fields
        )
        assert reply["error"]["code"] == "unauthorized"
    reply = await _ask(
        hass, hass_ws_client, entry, "ci_read", hass_read_only_access_token, code="APC", key={}
    )
    assert reply["success"], reply


async def test_unknown_receiver(
    hass: HomeAssistant, entry: MockConfigEntry, hass_ws_client: WebSocketGenerator
) -> None:
    await setup(hass, entry)
    client = await hass_ws_client(hass)
    await client.send_json_auto_id({"type": "onkyo_eiscp/ci_info", "entry_id": "nope"})
    reply = await client.receive_json()
    assert reply["error"]["code"] == "receiver_not_found"


async def test_a_receiver_without_ci_settings_reports_none(
    hass: HomeAssistant, entry: MockConfigEntry, hass_ws_client: WebSocketGenerator
) -> None:
    from unittest.mock import patch  # noqa: PLC0415

    from custom_components.onkyo_eiscp.lib import NoReplyError  # noqa: PLC0415

    await setup(hass, entry)
    with patch.object(entry.runtime_data.receiver, "ci_read", side_effect=NoReplyError("sAPC")):
        reply = await _ask(hass, hass_ws_client, entry, "ci_info")
    assert reply["result"] == {"supported": False, "families": [], "retry": False}


async def test_silence_in_standby_is_not_remembered(
    hass: HomeAssistant, entry: MockConfigEntry, hass_ws_client: WebSocketGenerator
) -> None:
    from unittest.mock import patch  # noqa: PLC0415

    from custom_components.onkyo_eiscp.lib import NoReplyError  # noqa: PLC0415

    await setup(hass, entry)
    receiver = entry.runtime_data.receiver
    with (
        patch.object(receiver, "ci_read", side_effect=NoReplyError("sAPC")),
        patch.dict(receiver._values, {"PWR": "00"}),
    ):
        reply = await _ask(hass, hass_ws_client, entry, "ci_info")
    assert reply["result"]["retry"] is True
    assert entry.runtime_data.ci_supported is None
    again = await _ask(hass, hass_ws_client, entry, "ci_info")
    assert again["result"]["supported"] is True


async def test_a_failed_read_back_still_offers_restore(
    hass: HomeAssistant, entry: MockConfigEntry, hass_ws_client: WebSocketGenerator
) -> None:
    from unittest.mock import patch  # noqa: PLC0415

    from custom_components.onkyo_eiscp.lib import NoReplyError  # noqa: PLC0415

    await setup(hass, entry)
    key = {"MM": "MM1"}
    receiver = entry.runtime_data.receiver
    with patch.object(receiver, "_ci_read_back", side_effect=NoReplyError("sLCC")):
        failed = await _ask(
            hass, hass_ws_client, entry, "ci_set", code="LCC", key=key, changes={"SW": "-29"}
        )
    assert failed["error"]["code"] == "ci_no_reply"
    read = await _ask(hass, hass_ws_client, entry, "ci_read", code="LCC", key=key)
    assert read["result"]["records"][0]["restorable"] == ["SW"]
    done = await _ask(hass, hass_ws_client, entry, "ci_restore", code="LCC", key=key)
    assert done["result"]["fields"]["SW"] == "-30"


async def test_network_settings_need_an_administrator(
    hass: HomeAssistant,
    entry: MockConfigEntry,
    hass_ws_client: WebSocketGenerator,
    hass_read_only_access_token: str,
) -> None:
    await setup(hass, entry)
    reply = await _ask(
        hass, hass_ws_client, entry, "ci_read", hass_read_only_access_token, code="NTC"
    )
    assert reply["error"]["code"] == "ci_refused"
