"""The core-conflict repair."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

from homeassistant.config_entries import (
    SIGNAL_CONFIG_ENTRY_CHANGED,
    ConfigEntryChange,
    ConfigEntryDisabler,
)
from homeassistant.const import CONF_HOST
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.dispatcher import async_dispatcher_send
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.onkyo_eiscp.const import CORE_DOMAIN, DOMAIN, ISSUE_CORE_CONFLICT
from custom_components.onkyo_eiscp.repairs import (
    DATA_CORE_ENTRY,
    async_check_core_conflict,
    async_create_fix_flow,
)
from tests.ha.conftest import setup


def _issue(hass: HomeAssistant, entry: MockConfigEntry) -> ir.IssueEntry | None:
    return ir.async_get(hass).async_get_issue(DOMAIN, f"{ISSUE_CORE_CONFLICT}_{entry.entry_id}")


async def test_no_core_entry_no_issue(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    await setup(hass, entry)
    assert _issue(hass, entry) is None


async def test_core_entry_on_the_same_host_raises_the_repair(
    hass: HomeAssistant, entry: MockConfigEntry
) -> None:
    core = MockConfigEntry(domain=CORE_DOMAIN, data={CONF_HOST: "127.0.0.1"})
    core.add_to_hass(hass)
    other = MockConfigEntry(domain=CORE_DOMAIN, data={CONF_HOST: "10.0.0.9"})
    other.add_to_hass(hass)
    await setup(hass, entry)
    issue = _issue(hass, entry)
    assert issue is not None
    assert issue.is_fixable
    assert issue.severity is ir.IssueSeverity.ERROR
    assert issue.data == {DATA_CORE_ENTRY: core.entry_id}
    assert issue.translation_placeholders is not None
    assert issue.translation_placeholders["host"] == "127.0.0.1"


async def test_repair_clears_when_the_core_entry_is_gone(
    hass: HomeAssistant, entry: MockConfigEntry
) -> None:
    core = MockConfigEntry(domain=CORE_DOMAIN, data={CONF_HOST: "127.0.0.1"})
    core.add_to_hass(hass)
    await setup(hass, entry)
    assert _issue(hass, entry) is not None
    with patch("custom_components.onkyo_eiscp.repairs.core_entries_on", return_value=[]):
        async_check_core_conflict(hass, entry)
    assert _issue(hass, entry) is None


async def test_fix_flow_removes_the_core_entry(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    core = MockConfigEntry(domain=CORE_DOMAIN, data={CONF_HOST: "127.0.0.1"})
    core.add_to_hass(hass)
    await setup(hass, entry)
    issue = _issue(hass, entry)
    assert issue is not None
    flow = await async_create_fix_flow(hass, issue.issue_id, issue.data)
    flow.hass = hass
    flow.handler = DOMAIN
    flow.issue_id = issue.issue_id
    shown = await flow.async_step_init()
    assert shown["type"] is FlowResultType.FORM
    assert hass.config_entries.async_get_entry(core.entry_id) is not None
    # The core integration's own unload code needs its library, so the removal is stubbed.
    with patch.object(hass.config_entries, "async_remove", AsyncMock()) as remove:
        done = await flow.async_step_confirm({})
    assert done["type"] is FlowResultType.CREATE_ENTRY
    remove.assert_awaited_once_with(core.entry_id)


async def test_removing_our_entry_clears_the_repair(
    hass: HomeAssistant, entry: MockConfigEntry
) -> None:
    MockConfigEntry(domain=CORE_DOMAIN, data={CONF_HOST: "127.0.0.1"}).add_to_hass(hass)
    await setup(hass, entry)
    assert _issue(hass, entry) is not None
    await hass.config_entries.async_remove(entry.entry_id)
    assert _issue(hass, entry) is None


async def test_core_entry_added_after_ours_raises_and_removal_clears(
    hass: HomeAssistant, entry: MockConfigEntry
) -> None:
    await setup(hass, entry)
    assert _issue(hass, entry) is None
    core = MockConfigEntry(domain=CORE_DOMAIN, data={CONF_HOST: "127.0.0.1"})
    core.add_to_hass(hass)
    async_dispatcher_send(hass, SIGNAL_CONFIG_ENTRY_CHANGED, ConfigEntryChange.ADDED, core)
    await hass.async_block_till_done()
    assert _issue(hass, entry) is not None
    with patch("custom_components.onkyo_eiscp.repairs.core_entries_on", return_value=[]):
        async_dispatcher_send(hass, SIGNAL_CONFIG_ENTRY_CHANGED, ConfigEntryChange.REMOVED, core)
        await hass.async_block_till_done()
    assert _issue(hass, entry) is None


async def test_disabled_core_entry_is_no_conflict(
    hass: HomeAssistant, entry: MockConfigEntry
) -> None:
    MockConfigEntry(
        domain=CORE_DOMAIN,
        data={CONF_HOST: "127.0.0.1"},
        disabled_by=ConfigEntryDisabler.USER,
    ).add_to_hass(hass)
    await setup(hass, entry)
    assert _issue(hass, entry) is None
