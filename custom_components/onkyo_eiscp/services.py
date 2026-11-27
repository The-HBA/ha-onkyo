"""Actions: ``send_raw`` (any eISCP message) and ``survey`` (a read-only capture of every code)."""

from __future__ import annotations

import asyncio
import re
from typing import TYPE_CHECKING, Any

import probatio
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant, ServiceCall, SupportsResponse
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.service import async_register_admin_service
from homeassistant.util import dt as dt_util

from .const import (
    ATTR_CONFIG_ENTRY_ID,
    ATTR_MESSAGE,
    DOMAIN,
    ERROR_NOT_CONNECTED,
    SERVICE_SEND_RAW,
    SERVICE_SURVEY,
)
from .entity import translated_errors
from .lib import COMMANDS, NoReplyError
from .lib.capabilities import queryable_codes
from .lib.commands import Value

if TYPE_CHECKING:
    from . import OnkyoConfigEntry
    from .coordinator import OnkyoCoordinator

#: Queries sent at once during a survey (one request per code is allowed, C3).
SURVEY_BATCH = 8
IP_PATTERN = re.compile(r"\d{1,3}(?:\. ?\d{1,3}){3}")

SEND_RAW_SCHEMA = probatio.Schema(
    {
        probatio.Required(ATTR_CONFIG_ENTRY_ID): str,
        probatio.Required(ATTR_MESSAGE): probatio.All(str, probatio.Length(min=1, max=200)),
    }
)
SURVEY_SCHEMA = probatio.Schema({probatio.Required(ATTR_CONFIG_ENTRY_ID): str})


def async_setup_services(hass: HomeAssistant) -> None:
    """Register the actions (once, from ``async_setup``; both need an admin user)."""
    async_register_admin_service(
        hass,
        DOMAIN,
        SERVICE_SEND_RAW,
        _send_raw,
        SEND_RAW_SCHEMA,
        SupportsResponse.ONLY,
    )
    async_register_admin_service(
        hass,
        DOMAIN,
        SERVICE_SURVEY,
        _survey,
        SURVEY_SCHEMA,
        SupportsResponse.ONLY,
    )


def _coordinator(hass: HomeAssistant, entry_id: str) -> OnkyoCoordinator:
    """Return the coordinator of a loaded entry, or raise a translated error."""
    entry: OnkyoConfigEntry | None = hass.config_entries.async_get_entry(entry_id)
    if entry is None or entry.domain != DOMAIN:
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="unknown_entry",
            translation_placeholders={"entry": entry_id},
        )
    if entry.state is not ConfigEntryState.LOADED:
        raise ServiceValidationError(translation_domain=DOMAIN, translation_key=ERROR_NOT_CONNECTED)
    return entry.runtime_data


async def _send_raw(call: ServiceCall) -> dict[str, Any]:
    """Send one message such as ``PWRQSTN`` or ``!1PWRQSTN`` and return what came back."""
    coordinator = _coordinator(call.hass, call.data[ATTR_CONFIG_ENTRY_ID])
    message = call.data[ATTR_MESSAGE].strip().removeprefix("!1")
    with translated_errors():
        replies = await coordinator.receiver.send_raw(message)
    return {"replies": replies}


async def _survey(call: ServiceCall) -> dict[str, Any]:
    """Ask for every known code (read only) and return a capture in the C1 summary shape."""
    coordinator = _coordinator(call.hass, call.data[ATTR_CONFIG_ENTRY_ID])
    receiver = coordinator.receiver
    caps = receiver.capabilities
    state = "on" if receiver.values.get("PWR") == "01" else "standby"
    # NRI (XML) holds the MAC address, the friendly name and the network services: not shared.
    codes = [code for code in queryable_codes() if COMMANDS[code].value is not Value.XML]
    private = [caps.mac, receiver.host]
    found: dict[str, Any] = {}

    async def ask(code: str) -> None:
        try:
            reply = await receiver.query(code)
        except NoReplyError, TimeoutError:
            return  # silent codes are left out, as in the receiver's own captures
        for secret in private:
            if secret:
                reply = re.sub(re.escape(secret), "removed", reply, flags=re.IGNORECASE)
        reply = IP_PATTERN.sub("removed", reply)
        found[code] = {
            "zone": COMMANDS[code].zone.value,
            "states": {state: reply},
            "writes": [],
            "notes": "",
        }

    with translated_errors():  # a lost connection stops the survey instead of thinning it
        for start in range(0, len(codes), SURVEY_BATCH):
            await asyncio.gather(*(ask(code) for code in codes[start : start + SURVEY_BATCH]))
    return {
        "model": caps.model,
        "firmware": caps.firmware,
        "captured": dt_util.now().date().isoformat(),
        "codes": dict(sorted(found.items())),
    }
