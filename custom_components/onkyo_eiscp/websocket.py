"""Websocket commands for the remote card (ARCHITECTURE.md C5 and C6).

Every command names the receiver by its config entry ID (``entry_id``) or its device ID
(``device_id``). Errors carry a ``code`` the card can act on: ``receiver_not_found``,
``invalid_names`` and ``name_in_use``. Writes need an administrator.

``onkyo_eiscp/card_info`` gives the card what it cannot read from entity states: the zones, the
volume scale, the listening mode groups, the filled Dirac slots and, for the Edit sheet, the
full lists of inputs and listening modes with their stored names. It holds no host and no MAC.
``onkyo_eiscp/set_names`` writes those names, the hidden flags and the input order, the same
options the options flow writes, then reloads the entry so every list follows.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Final

import probatio
from homeassistant.components import websocket_api
from homeassistant.components.websocket_api import messages as ws_messages
from homeassistant.components.websocket_api.decorators import (
    async_response,
    require_admin,
    websocket_command,
)
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import callback
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import device_registry as dr
from homeassistant.loader import async_get_integration

from .const import (
    CONF_HIDDEN,
    CONF_INPUT_ORDER,
    CONF_INPUTS,
    CONF_LISTENING_MODES,
    CONF_MAX_VOLUME,
    CONF_NAME,
    DOMAIN,
    WS_CARD_INFO,
    ZONE_MAIN,
)
from .lib import CodecError
from .lib.codecs import decode_slots
from .lib.commands import COMMANDS, LISTENING_MODES
from .naming import ordered_input_codes, table_mode_name

if TYPE_CHECKING:
    from homeassistant.components.websocket_api.connection import ActiveConnection
    from homeassistant.core import HomeAssistant

    from . import OnkyoConfigEntry
    from .lib import Capabilities

ATTR_ENTRY_ID: Final = "entry_id"
ATTR_DEVICE_ID: Final = "device_id"
ATTR_KIND: Final = "kind"
ATTR_NAMES: Final = "names"
ATTR_ORDER: Final = "order"

WS_SET_NAMES: Final = "onkyo_eiscp/set_names"
KIND_INPUTS: Final = "inputs"
KIND_MODES: Final = "modes"

ERR_RECEIVER_NOT_FOUND: Final = "receiver_not_found"
ERR_INVALID_NAMES: Final = "invalid_names"
ERR_NAME_IN_USE: Final = "name_in_use"
#: Longer names do not fit the card's buttons.
MAX_NAME_LENGTH: Final = 32

_TARGET: Final = {
    probatio.Exclusive(ATTR_ENTRY_ID, "receiver"): str,
    probatio.Exclusive(ATTR_DEVICE_ID, "receiver"): str,
}


class NamesError(Exception):
    """The names sent by the card cannot be stored."""

    def __init__(self, code: str, message: str) -> None:
        """Keep the error ``code`` the card acts on."""
        super().__init__(message)
        self.code = code


def _command(command: str, fields: dict[Any, Any] | None = None) -> probatio.All[Any]:
    """Return a command schema that needs ``entry_id`` or ``device_id``."""
    return probatio.All(
        ws_messages.BASE_COMMAND_MESSAGE_SCHEMA.extend(
            {probatio.Required("type"): command, **_TARGET, **(fields or {})}
        ),
        cv.has_at_least_one_key(ATTR_ENTRY_ID, ATTR_DEVICE_ID),
    )


@callback
def async_register_commands(hass: HomeAssistant) -> None:
    """Register the integration's websocket commands (once, in ``async_setup``)."""
    websocket_api.async_register_command(hass, ws_card_info)
    websocket_api.async_register_command(hass, ws_set_names)


def _entry(hass: HomeAssistant, msg: dict[str, Any]) -> OnkyoConfigEntry:
    """Return the loaded config entry the message names."""
    entry_id: str | None = msg.get(ATTR_ENTRY_ID)
    if (device_id := msg.get(ATTR_DEVICE_ID)) is not None:
        device = dr.async_get(hass).async_get(device_id)
        candidates = device.config_entries if device else set()
        entry_id = next(
            (
                candidate
                for candidate in candidates
                if (found := hass.config_entries.async_get_entry(candidate))
                and found.domain == DOMAIN
            ),
            None,
        )
    entry = hass.config_entries.async_get_entry(entry_id) if entry_id else None
    if entry is None or entry.domain != DOMAIN or entry.state is not ConfigEntryState.LOADED:
        raise NamesError(ERR_RECEIVER_NOT_FOUND, "No loaded receiver matches")
    return entry


def _device_id(hass: HomeAssistant, entry: OnkyoConfigEntry, caps: Capabilities) -> str | None:
    device = dr.async_get(hass).async_get_device_by_identifier(
        (DOMAIN, caps.mac.lower()), entry.entry_id
    )
    return device.id if device else None


def _stored(options: Any, section: str, code: str) -> dict[str, Any]:  # noqa: ANN401
    value = (options.get(section) or {}).get(code)
    return value if isinstance(value, dict) else {}


def _volume_max(entry: OnkyoConfigEntry, caps: Capabilities) -> int:
    """Raw volume that counts as 100 % (the same rule as the media player)."""
    zone = caps.zone(ZONE_MAIN)
    top = zone.volume_max if zone else 100
    chosen = entry.options.get(CONF_MAX_VOLUME)
    return min(int(chosen), top) if chosen is not None else top


def _filled_slots(values: dict[str, str]) -> list[str]:
    try:
        return list(decode_slots(values.get("DSS", "")).filled)
    except CodecError:
        return []


def card_info(hass: HomeAssistant, entry: OnkyoConfigEntry, version: str | None) -> dict[str, Any]:
    """Build the ``card_info`` answer for one loaded entry."""
    data = entry.runtime_data.data
    caps = data.capabilities
    options = entry.options
    zone = caps.zone(ZONE_MAIN)
    names = {item.code: item.name for item in caps.inputs}
    return {
        "entry_id": entry.entry_id,
        "device_id": _device_id(hass, entry, caps),
        "model": caps.model,
        "version": version,
        "zones": [item.id for item in caps.zones],
        "volume_max": _volume_max(entry, caps),
        "volume_db_step": 0.5 if zone and zone.half_db else None,
        "dirac_slots": _filled_slots(dict(data.values)),
        "remote_keys": [
            COMMANDS["OSD"].options[param]
            for param in caps.options.get("OSD", ())
            if param in COMMANDS["OSD"].options
        ],
        "listening_mode_groups": {
            code: LISTENING_MODES[code].group.value
            for code in caps.listening_modes
            if code in LISTENING_MODES
        },
        "inputs": [
            {
                "code": code,
                "name": names.get(code, code),
                "custom": str(_stored(options, CONF_INPUTS, code).get(CONF_NAME) or ""),
                "hidden": bool(_stored(options, CONF_INPUTS, code).get(CONF_HIDDEN, False)),
                "zones": sorted(
                    zone_id for item in caps.inputs if item.code == code for zone_id in item.zones
                ),
            }
            for code in ordered_input_codes(caps, options)
        ],
        "listening_modes": [
            {
                "code": code,
                "name": table_mode_name(code),
                "custom": str(_stored(options, CONF_LISTENING_MODES, code).get(CONF_NAME) or ""),
                "hidden": bool(
                    _stored(options, CONF_LISTENING_MODES, code).get(CONF_HIDDEN, False)
                ),
                "group": LISTENING_MODES[code].group.value if code in LISTENING_MODES else "other",
            }
            for code in caps.listening_modes
        ],
    }


def _send_error(connection: ActiveConnection, msg_id: int, err: NamesError) -> None:
    connection.send_error(msg_id, err.code, str(err))


@websocket_command(_command(WS_CARD_INFO))
@async_response
async def ws_card_info(
    hass: HomeAssistant, connection: ActiveConnection, msg: dict[str, Any]
) -> None:
    """Return what the card needs besides entity states."""
    try:
        entry = _entry(hass, msg)
    except NamesError as err:
        _send_error(connection, msg["id"], err)
        return
    integration = await async_get_integration(hass, DOMAIN)
    version = str(integration.version) if integration.version else None
    connection.send_result(msg["id"], card_info(hass, entry, version))


_NAME_ITEM: Final = {
    probatio.Optional(CONF_NAME): str,
    probatio.Optional(CONF_HIDDEN): bool,
}


@websocket_command(
    _command(
        WS_SET_NAMES,
        {
            probatio.Required(ATTR_KIND): probatio.In([KIND_INPUTS, KIND_MODES]),
            probatio.Required(ATTR_NAMES): {str: _NAME_ITEM},
            probatio.Optional(ATTR_ORDER): [str],
        },
    )
)
@require_admin
@async_response
async def ws_set_names(
    hass: HomeAssistant, connection: ActiveConnection, msg: dict[str, Any]
) -> None:
    """Store names, hidden flags and the input order, then reload the entry."""
    try:
        entry = _entry(hass, msg)
        options = _new_options(entry, msg)
    except NamesError as err:
        _send_error(connection, msg["id"], err)
        return
    hass.config_entries.async_update_entry(entry, options=options)
    await hass.config_entries.async_reload(entry.entry_id)
    connection.send_result(msg["id"])


def _new_options(entry: OnkyoConfigEntry, msg: dict[str, Any]) -> dict[str, Any]:
    """Return the entry's options with the names of one kind replaced."""
    caps = entry.runtime_data.data.capabilities
    kind: str = msg[ATTR_KIND]
    sent: dict[str, dict[str, Any]] = msg[ATTR_NAMES]
    if kind == KIND_INPUTS:
        section = CONF_INPUTS
        defaults = {item.code: item.name for item in caps.inputs}
    else:
        section = CONF_LISTENING_MODES
        defaults = {code: table_mode_name(code) for code in caps.listening_modes}
    if unknown := sorted(set(sent) - set(defaults)):
        raise NamesError(ERR_INVALID_NAMES, f"Unknown codes: {', '.join(unknown)}")

    stored: dict[str, dict[str, Any]] = {}
    shown: dict[str, str] = {}
    for code, default in defaults.items():
        item = sent.get(code, {})
        name = str(item.get(CONF_NAME, "")).strip()
        if len(name) > MAX_NAME_LENGTH:
            raise NamesError(ERR_INVALID_NAMES, f"Names are at most {MAX_NAME_LENGTH} characters")
        hidden = bool(item.get(CONF_HIDDEN, False))
        shown[code] = name or default
        if name == default:
            name = ""
        if name or hidden:
            stored[code] = {CONF_NAME: name, CONF_HIDDEN: hidden}
    taken: set[str] = set()
    for label in shown.values():
        key = label.casefold()
        if key in taken:
            raise NamesError(ERR_NAME_IN_USE, f"Another entry is already named {label!r}")
        taken.add(key)

    options = dict(entry.options)
    options[section] = stored
    if kind == KIND_INPUTS and ATTR_ORDER in msg:
        _apply_order(options, caps, msg[ATTR_ORDER])
    return options


def _apply_order(options: dict[str, Any], caps: Capabilities, order: list[str]) -> None:
    """Store the input order; the receiver's own order is stored as no order."""
    receiver_order = [item.code for item in caps.inputs]
    if unknown := [code for code in order if code not in receiver_order]:
        raise NamesError(ERR_INVALID_NAMES, f"Unknown inputs: {', '.join(unknown)}")
    chosen = list(dict.fromkeys(order))
    rest = [code for code in receiver_order if code not in chosen]
    if chosen + rest == receiver_order:
        options.pop(CONF_INPUT_ORDER, None)
    else:
        options[CONF_INPUT_ORDER] = chosen
