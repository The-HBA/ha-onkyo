"""Config flow: manual host, SSDP, duplicates and reconfigure."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from unittest.mock import AsyncMock, patch

from homeassistant import config_entries
from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers.service_info.ssdp import SsdpServiceInfo
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.onkyo_eiscp.const import DOMAIN
from custom_components.onkyo_eiscp.lib.codecs import parse_device_info
from tests.ha.conftest import MAC
from tools.eiscp_sim import SimServer

NRI = (Path(__file__).parents[1] / "fixtures" / "tx-rz50" / "nri.xml").read_text()
READ = "custom_components.onkyo_eiscp.config_flow.read_device_info"


async def test_user_flow_creates_entry(hass: HomeAssistant, sim: SimServer) -> None:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_HOST: "127.0.0.1", CONF_PORT: sim.port}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Onkyo TX-RZ50"
    assert result["data"] == {CONF_HOST: "127.0.0.1", CONF_PORT: sim.port}
    assert result["result"].unique_id == MAC
    await hass.async_block_till_done()


async def test_user_flow_cannot_connect(hass: HomeAssistant) -> None:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    with patch(READ, AsyncMock(side_effect=OSError)):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_HOST: "10.0.0.9", CONF_PORT: 60128}
        )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "cannot_connect"}


async def test_user_flow_without_identity(hass: HomeAssistant) -> None:
    info = replace(parse_device_info(NRI), mac="")
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    with patch(READ, AsyncMock(return_value=info)):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_HOST: "10.0.0.9", CONF_PORT: 60128}
        )
    assert result["errors"] == {"base": "no_identity"}


async def test_same_host_never_probed_twice(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    entry.add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    with patch(READ, AsyncMock()) as read:
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_HOST: "127.0.0.1", CONF_PORT: 60128}
        )
    read.assert_not_called()
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_same_receiver_on_new_host_updates_the_entry(
    hass: HomeAssistant, entry: MockConfigEntry
) -> None:
    entry.add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    with patch(READ, AsyncMock(return_value=parse_device_info(NRI))):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_HOST: "10.0.0.77", CONF_PORT: 60128}
        )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"
    assert entry.data[CONF_HOST] == "10.0.0.77"


def _ssdp(host: str = "10.0.0.5", udn: str = f"uuid:4f6e-{MAC}") -> SsdpServiceInfo:
    return SsdpServiceInfo(
        ssdp_usn="usn",
        ssdp_st="urn:schemas-upnp-org:device:MediaRenderer:1",
        ssdp_location=f"http://{host}:8080/description.xml",
        ssdp_udn=udn,
        upnp={},
    )


async def test_ssdp_flow(hass: HomeAssistant) -> None:
    with patch(READ, AsyncMock(return_value=parse_device_info(NRI))):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_SSDP}, data=_ssdp()
        )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "confirm"
    with patch("custom_components.onkyo_eiscp.async_setup_entry", AsyncMock(return_value=True)):
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"] == {CONF_HOST: "10.0.0.5", CONF_PORT: 60128}
    assert result["result"].unique_id == MAC
    await hass.async_block_till_done()


async def test_ssdp_known_receiver_updates_host(
    hass: HomeAssistant, entry: MockConfigEntry
) -> None:
    entry.add_to_hass(hass)
    with patch(READ, AsyncMock()) as read:
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_SSDP}, data=_ssdp("10.0.0.6")
        )
    read.assert_not_called()
    assert result["type"] is FlowResultType.ABORT
    assert entry.data[CONF_HOST] == "10.0.0.6"


async def test_ssdp_unreachable_aborts(hass: HomeAssistant) -> None:
    with patch(READ, AsyncMock(side_effect=TimeoutError)):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_SSDP}, data=_ssdp(udn="")
        )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "cannot_connect"


async def test_reconfigure(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    entry.add_to_hass(hass)
    result = await entry.start_reconfigure_flow(hass)
    assert result["type"] is FlowResultType.FORM
    other = parse_device_info(NRI)
    with (
        patch(READ, AsyncMock(return_value=other)),
        patch("custom_components.onkyo_eiscp.async_setup_entry", AsyncMock(return_value=True)),
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_HOST: "10.0.0.8", CONF_PORT: 60128}
        )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert entry.data[CONF_HOST] == "10.0.0.8"


async def test_reconfigure_rejects_another_receiver(
    hass: HomeAssistant, entry: MockConfigEntry
) -> None:
    entry.add_to_hass(hass)
    result = await entry.start_reconfigure_flow(hass)
    other = parse_device_info(NRI.replace("0009B0000001", "0009B0000002"))
    with patch(READ, AsyncMock(return_value=other)):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_HOST: "10.0.0.8", CONF_PORT: 60128}
        )
    assert result["errors"] == {"base": "wrong_device"}
