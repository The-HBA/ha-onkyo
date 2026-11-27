"""The core-conflict repair: core ``onkyo`` and this integration on one host (ARCHITECTURE.md C5).

The receiver closes the older connection when the same computer opens a second one, so the two
integrations would push each other off. The repair tells the user and offers to remove the core
entry.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.components.repairs import ConfirmRepairFlow, RepairsFlow
from homeassistant.const import CONF_HOST
from homeassistant.helpers import issue_registry as ir

from .const import CORE_DOMAIN, DOMAIN, ISSUE_CORE_CONFLICT

if TYPE_CHECKING:
    from homeassistant.components.repairs.models import RepairsFlowResult
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant

    from . import OnkyoConfigEntry

DATA_CORE_ENTRY = "core_entry_id"


def _same_host(left: object, right: object) -> bool:
    return str(left).strip().casefold() == str(right).strip().casefold()


def core_entries_on(hass: HomeAssistant, host: str) -> list[ConfigEntry]:
    """Return the core ``onkyo`` entries that use ``host``."""
    return [
        entry
        for entry in hass.config_entries.async_entries(CORE_DOMAIN)
        if _same_host(entry.data.get(CONF_HOST, ""), host)
    ]


def _issue_id(entry: OnkyoConfigEntry) -> str:
    return f"{ISSUE_CORE_CONFLICT}_{entry.entry_id}"


def async_check_core_conflict(hass: HomeAssistant, entry: OnkyoConfigEntry) -> None:
    """Raise the repair while a core entry shares the host, clear it when none does."""
    host = entry.data.get(CONF_HOST, "")
    core = core_entries_on(hass, host)
    if not core:
        ir.async_delete_issue(hass, DOMAIN, _issue_id(entry))
        return
    ir.async_create_issue(
        hass,
        DOMAIN,
        _issue_id(entry),
        data={DATA_CORE_ENTRY: core[0].entry_id},
        is_fixable=True,
        severity=ir.IssueSeverity.ERROR,
        translation_key=ISSUE_CORE_CONFLICT,
        translation_placeholders={"host": str(host), "title": entry.title},
    )


def async_clear_core_conflict(hass: HomeAssistant, entry: OnkyoConfigEntry) -> None:
    """Drop the repair when the entry is removed."""
    ir.async_delete_issue(hass, DOMAIN, _issue_id(entry))


class CoreConflictRepairFlow(ConfirmRepairFlow):
    """Ask once, then remove the core entry that shares the receiver."""

    def __init__(self, core_entry_id: str) -> None:
        """Remember which core entry to remove."""
        super().__init__()
        self._core_entry_id = core_entry_id

    async def async_step_confirm(
        self, user_input: dict[str, str] | None = None
    ) -> RepairsFlowResult:
        """Remove the core entry after the user confirms."""
        if user_input is not None and self.hass.config_entries.async_get_entry(self._core_entry_id):
            await self.hass.config_entries.async_remove(self._core_entry_id)
        return await super().async_step_confirm(user_input)


async def async_create_fix_flow(
    hass: HomeAssistant,  # noqa: ARG001
    issue_id: str,  # noqa: ARG001
    data: dict[str, str | int | float | None] | None,
) -> RepairsFlow:
    """Create the flow that offers to remove the core entry."""
    return CoreConflictRepairFlow(str((data or {}).get(DATA_CORE_ENTRY, "")))
