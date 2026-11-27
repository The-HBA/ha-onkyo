"""Diagnostics: what the receiver reported, without addresses or identifiers."""

from __future__ import annotations

from dataclasses import asdict
from typing import TYPE_CHECKING, Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.const import CONF_HOST

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

    from . import OnkyoConfigEntry

TO_REDACT = {CONF_HOST, "mac", "unique_id", "friendly_name"}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant,  # noqa: ARG001
    entry: OnkyoConfigEntry,
) -> dict[str, Any]:
    """Return the entry, the capabilities and the last values."""
    data = entry.runtime_data.data
    caps = data.capabilities
    capabilities = {
        "model": caps.model,
        "brand": caps.brand,
        "mac": caps.mac,
        "firmware": caps.firmware,
        "zones": [asdict(zone) for zone in caps.zones],
        "inputs": [
            {"code": item.code, "name": item.name, "zones": sorted(item.zones)}
            for item in caps.inputs
        ],
        "supported": sorted(caps.supported),
        "listening_modes": list(caps.listening_modes),
        "signal_modes": {name: list(codes) for name, codes in caps.signal_modes.items()},
        "options": {code: list(values) for code, values in caps.options.items()},
        "values": dict(caps.values),
    }
    return async_redact_data(
        {
            "entry": {"data": dict(entry.data), "options": dict(entry.options)},
            "connected": data.connected,
            "unavailable": sorted(data.unavailable),
            "values": dict(data.values),
            "capabilities": capabilities,
        },
        TO_REDACT,
    )
