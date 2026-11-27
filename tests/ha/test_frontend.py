"""Serving the card and registering it with the dashboards and the sidebar."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from homeassistant.components.frontend import DATA_EXTRA_MODULE_URL, DATA_PANELS
from homeassistant.components.lovelace.const import LOVELACE_DATA
from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.core import HomeAssistant
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.typing import ClientSessionGenerator

from custom_components.onkyo_eiscp.const import DOMAIN
from custom_components.onkyo_eiscp.frontend import CARD_PATH, DATA_FRONTEND, PANEL_PATH
from tests.ha.conftest import MAC, setup
from tools.eiscp_sim import SimServer

COMPONENT = Path(__file__).parents[2] / "custom_components" / "onkyo_eiscp"
VERSION = json.loads((COMPONENT / "manifest.json").read_text(encoding="utf-8"))["version"]
CARD_URL = f"{CARD_PATH}?v={VERSION}"
PANEL_URL = f"{PANEL_PATH}?v={VERSION}"


def _resources(hass: HomeAssistant) -> list[dict[str, Any]]:
    return list(hass.data[LOVELACE_DATA].resources.async_items())


def _card_resources(hass: HomeAssistant) -> list[dict[str, Any]]:
    return [item for item in _resources(hass) if item["url"].startswith(CARD_PATH)]


def _stored(*urls: str) -> dict[str, Any]:
    return {
        "version": 1,
        "minor_version": 1,
        "key": "lovelace_resources",
        "data": {
            "items": [
                {"id": f"id{index}", "type": "module", "url": url} for index, url in enumerate(urls)
            ]
        },
    }


def _second_entry(sim: SimServer) -> MockConfigEntry:
    """Another entry (the same simulator, another unique ID): only the frontend bookkeeping runs."""
    return MockConfigEntry(
        domain=DOMAIN,
        unique_id="0009b0000002",
        title="Second",
        data={CONF_HOST: "127.0.0.1", CONF_PORT: sim.port},
    )


@pytest.fixture
async def dashboards(hass: HomeAssistant) -> None:
    """Load the dashboards (storage mode), as a normal Home Assistant has them."""
    assert await async_setup_component(hass, "lovelace", {})


def _has_panel(hass: HomeAssistant) -> bool:
    return "onkyo" in hass.data.get(DATA_PANELS, {})


async def test_card_files_are_served(
    hass: HomeAssistant,
    entry: MockConfigEntry,
    hass_client_no_auth: ClientSessionGenerator,
) -> None:
    await setup(hass, entry)
    client = await hass_client_no_auth()
    for name, element in (
        ("onkyo-remote-card.js", "onkyo-remote-card"),
        ("onkyo-remote-card-editor.js", "onkyo-remote-card-editor"),
        ("onkyo-panel.js", "onkyo-panel"),
        ("shared.js", "onkyo_eiscp/card_info"),
        ("rename-sheet.js", "Rename listening modes"),
        ("tabs/main.js", 'id: "main"'),
        ("tabs/modes.js", 'id: "modes"'),
    ):
        response = await client.get(f"/onkyo_eiscp_static/{name}?v={VERSION}")
        assert response.status == 200, name
        assert element in await response.text(), name


async def test_every_www_file_is_listed_by_a_test(hass: HomeAssistant) -> None:
    """A new file in www/ is a new thing the card loads: keep the list above honest."""
    files = sorted(
        path.relative_to(COMPONENT / "www").as_posix() for path in (COMPONENT / "www").rglob("*.js")
    )
    assert "onkyo-remote-card.js" in files
    assert all(not name.endswith(".ts") for name in files)


@pytest.mark.usefixtures("dashboards")
async def test_storage_mode_creates_one_resource(
    hass: HomeAssistant, entry: MockConfigEntry
) -> None:
    await setup(hass, entry)
    [resource] = _resources(hass)
    assert resource["type"] == "module"
    assert resource["url"] == CARD_URL


@pytest.mark.usefixtures("dashboards")
async def test_storage_mode_updates_an_old_version_and_drops_duplicates(
    hass: HomeAssistant, entry: MockConfigEntry, hass_storage: dict[str, Any]
) -> None:
    hass_storage["lovelace_resources"] = _stored(
        "/local/other.js", f"{CARD_PATH}?v=0.0.1", CARD_PATH
    )
    await setup(hass, entry)
    assert _resources(hass) == [
        {"id": "id0", "type": "module", "url": "/local/other.js"},
        {"id": "id1", "type": "module", "url": CARD_URL},
    ]


@pytest.mark.usefixtures("dashboards")
async def test_a_current_resource_is_kept(
    hass: HomeAssistant, entry: MockConfigEntry, hass_storage: dict[str, Any]
) -> None:
    hass_storage["lovelace_resources"] = _stored(CARD_URL)
    await setup(hass, entry)
    assert _resources(hass) == [{"id": "id0", "type": "module", "url": CARD_URL}]


@pytest.mark.usefixtures("dashboards")
async def test_registered_once_for_two_receivers_and_removed_with_the_last(
    hass: HomeAssistant, entry: MockConfigEntry, sim: SimServer
) -> None:
    second = _second_entry(sim)
    await setup(hass, entry)
    second.add_to_hass(hass)
    # Only the frontend part runs for the second entry: its receiver is the same simulator.
    from custom_components.onkyo_eiscp.frontend import async_setup_frontend  # noqa: PLC0415

    await async_setup_frontend(hass)
    assert [item["url"] for item in _card_resources(hass)] == [CARD_URL]

    await hass.config_entries.async_remove(second.entry_id)
    await hass.async_block_till_done()
    assert [item["url"] for item in _card_resources(hass)] == [CARD_URL]

    await hass.config_entries.async_remove(entry.entry_id)
    await hass.async_block_till_done()
    assert _card_resources(hass) == []
    assert hass.data[DATA_FRONTEND].card_url is None


async def test_yaml_resources_add_an_extra_module(
    hass: HomeAssistant, entry: MockConfigEntry
) -> None:
    assert await async_setup_component(hass, "lovelace", {"lovelace": {"resource_mode": "yaml"}})
    await setup(hass, entry)
    assert CARD_URL in hass.data[DATA_EXTRA_MODULE_URL].urls
    assert _resources(hass) == []


async def test_removing_an_entry_that_never_loaded_is_quiet(hass: HomeAssistant) -> None:
    dead = MockConfigEntry(
        domain=DOMAIN, unique_id=MAC, data={CONF_HOST: "127.0.0.1", CONF_PORT: 1}
    )
    dead.add_to_hass(hass)
    await hass.config_entries.async_remove(dead.entry_id)
    await hass.async_block_till_done()
    assert LOVELACE_DATA not in hass.data


async def test_sidebar_page_is_registered_and_follows_the_entry(
    hass: HomeAssistant, entry: MockConfigEntry
) -> None:
    await setup(hass, entry)
    panel = hass.data[DATA_PANELS]["onkyo"].to_response()
    assert panel["component_name"] == "custom"
    assert panel["title"] == "Onkyo"
    assert panel["icon"] == "mdi:audio-video"
    assert panel["require_admin"] is False
    custom = panel["config"]["_panel_custom"]
    assert custom["name"] == "onkyo-panel"
    assert custom["module_url"] == PANEL_URL
    assert custom["embed_iframe"] is False

    # A reload (a name change reloads the entry) keeps the page without a gap.
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert _has_panel(hass)

    assert await hass.config_entries.async_unload(entry.entry_id)
    assert _has_panel(hass)

    await hass.config_entries.async_remove(entry.entry_id)
    await hass.async_block_till_done()
    assert not _has_panel(hass)
    assert hass.data[DATA_FRONTEND].panel_url is None
