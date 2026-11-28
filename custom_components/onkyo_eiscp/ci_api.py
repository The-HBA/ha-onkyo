"""Websocket commands for the receiver's CI settings (the sidebar page's advanced settings).

The CI ("custom install") settings are the ones the receiver's removed Web Setup page held:
input and output assign, speaker levels, distances, crossovers, equalizer and more
(``lib/ci.py``, specs/web-setup-backup.md). Four commands, each naming the receiver like the
card commands do:

``onkyo_eiscp/ci_info``     which families the receiver answers, with their fields and keys.
``onkyo_eiscp/ci_read``     the records of one family (all its keys, or the one asked).
``onkyo_eiscp/ci_set``      change fields of one record (administrator); reads back.
``onkyo_eiscp/ci_restore``  put a calibration record back to what it held before the first
                            change of this session (administrator).

Calibration families (levels, distances, crossovers) remember the old values before the first
change, so the page can offer "restore". The speaker layout and the network are shown read-only
and the library refuses to write them.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Final

import probatio
from homeassistant.components import websocket_api
from homeassistant.components.websocket_api.decorators import (
    async_response,
    require_admin,
    websocket_command,
)

from .const import WS_CI_INFO, WS_CI_READ, WS_CI_RESTORE, WS_CI_SET
from .lib import ci
from .lib.exceptions import (
    CiNotAppliedError,
    CiRefusedError,
    CodecError,
    EiscpError,
    NoReplyError,
)
from .websocket import NamesError, _command, _entry, _send_error

if TYPE_CHECKING:
    from homeassistant.components.websocket_api.connection import ActiveConnection
    from homeassistant.core import HomeAssistant

    from .coordinator import OnkyoCoordinator
    from .lib import Capabilities

ATTR_CODE: Final = "code"
ATTR_KEY: Final = "key"
ATTR_CHANGES: Final = "changes"
ATTR_KEEP: Final = "keep"

ERR_CI_UNKNOWN: Final = "ci_unknown_family"
ERR_CI_REFUSED: Final = "ci_refused"
ERR_CI_INVALID: Final = "ci_invalid"
ERR_CI_NOT_APPLIED: Final = "ci_not_applied"
ERR_CI_NO_REPLY: Final = "ci_no_reply"
ERR_CI_NOTHING: Final = "ci_nothing_to_restore"
ERR_CI_RECEIVER: Final = "ci_receiver_error"

#: Families that are status only (not settings); the page never asks for them.
STATUS_FAMILIES: Final = frozenset({"MNC", "ST-", "AM-"})
#: Zone number in the MZC key to the zone ids of the capabilities.
_ZONE_KEYS: Final = {"002": "zone2", "003": "zone3"}

_KEY: Final = {str: str}


def _family(code: str) -> ci.FamilySpec:
    spec = ci.FAMILIES.get(code)
    if spec is None or code in STATUS_FAMILIES:
        raise NamesError(ERR_CI_UNKNOWN, f"Unknown settings family {code!r}")
    return spec


def _keys(spec: ci.FamilySpec, caps: Capabilities) -> list[dict[str, str]]:
    keys = list(spec.all_keys())
    if spec.code == "MZC":
        zones = {item.id for item in caps.zones}
        keys = [key for key in keys if _ZONE_KEYS.get(key["ZN"]) in zones]
    return keys


def _describe(spec: ci.FamilySpec, caps: Capabilities) -> dict[str, Any]:
    return {
        "code": spec.code,
        "title": spec.title,
        "calibration": spec.calibration,
        "writable": spec.writable,
        "reason": spec.reason,
        "key": [{"name": item.name, "values": list(item.values)} for item in spec.key],
        "keys": _keys(spec, caps),
        "shared": sorted(spec.shared),
        "fields": {
            name: {
                "width": item.width,
                "pattern": item.pattern,
                "writable": item.writable and name not in spec.key_names,
            }
            for name, item in spec.fields.items()
            if name not in spec.key_names
        },
    }


def _baseline_key(code: str, key: dict[str, str]) -> tuple[str, tuple[tuple[str, str], ...]]:
    return code, tuple(sorted((name, value.strip()) for name, value in key.items()))


def _restorable(coordinator: OnkyoCoordinator, code: str, key: dict[str, str]) -> list[str]:
    saved = coordinator.ci_baseline.get(_baseline_key(code, key))
    return [name for name, _ in saved.items] if saved is not None else []


def _saved(
    coordinator: OnkyoCoordinator, slot: tuple[str, tuple[tuple[str, str], ...]]
) -> ci.CiRecord:
    saved = coordinator.ci_baseline.get(slot)
    if saved is None:
        raise NamesError(ERR_CI_NOTHING, "Nothing to restore for this record")
    return saved


def _record(coordinator: OnkyoCoordinator, record: ci.CiRecord) -> dict[str, Any]:
    key = record.key
    return {
        "key": key,
        "fields": record.fields,
        "restorable": _restorable(coordinator, record.code, key),
    }


def _error(err: Exception) -> NamesError:
    """Map a library error to the error the page acts on."""
    if isinstance(err, CiRefusedError):
        return NamesError(ERR_CI_REFUSED, str(err))
    if isinstance(err, CiNotAppliedError):
        return NamesError(ERR_CI_NOT_APPLIED, "The receiver ignored the new value")
    if isinstance(err, NoReplyError):
        return NamesError(ERR_CI_NO_REPLY, "The receiver did not answer")
    if isinstance(err, CodecError):
        return NamesError(ERR_CI_INVALID, str(err))
    return NamesError(ERR_CI_RECEIVER, str(err))


async def _probe(coordinator: OnkyoCoordinator) -> bool:
    """Ask the receiver for one setting; a model without CI commands stays silent."""
    if coordinator.ci_supported is None:
        try:
            await coordinator.receiver.ci_read("APC")
        except NoReplyError:
            coordinator.ci_supported = False
        except EiscpError as err:
            raise _error(err) from err  # connection trouble: ask again next time
        else:
            coordinator.ci_supported = True
    return coordinator.ci_supported


def register(hass: HomeAssistant) -> None:
    """Register the CI commands (called from ``websocket.async_register_commands``)."""
    websocket_api.async_register_command(hass, ws_ci_info)
    websocket_api.async_register_command(hass, ws_ci_read)
    websocket_api.async_register_command(hass, ws_ci_set)
    websocket_api.async_register_command(hass, ws_ci_restore)


@websocket_command(_command(WS_CI_INFO))
@async_response
async def ws_ci_info(
    hass: HomeAssistant, connection: ActiveConnection, msg: dict[str, Any]
) -> None:
    """Say whether the receiver answers CI settings and describe every family."""
    try:
        entry = _entry(hass, msg)
        coordinator = entry.runtime_data
        async with coordinator.ci_lock:
            supported = await _probe(coordinator)
    except NamesError as err:
        _send_error(connection, msg["id"], err)
        return
    caps = coordinator.data.capabilities
    families = (
        [_describe(spec, caps) for code, spec in ci.FAMILIES.items() if code not in STATUS_FAMILIES]
        if supported
        else []
    )
    connection.send_result(msg["id"], {"supported": supported, "families": families})


@websocket_command(
    _command(
        WS_CI_READ,
        {
            probatio.Required(ATTR_CODE): str,
            probatio.Optional(ATTR_KEY): _KEY,
        },
    )
)
@async_response
async def ws_ci_read(
    hass: HomeAssistant, connection: ActiveConnection, msg: dict[str, Any]
) -> None:
    """Read the records of one family: the one named by ``key``, or every record."""
    try:
        entry = _entry(hass, msg)
        spec = _family(msg[ATTR_CODE])
        coordinator = entry.runtime_data
        asked: dict[str, str] | None = msg.get(ATTR_KEY)
        keys = [asked] if asked is not None else _keys(spec, coordinator.data.capabilities)
        records: list[dict[str, Any]] = []
        async with coordinator.ci_lock:
            for key in keys:
                try:
                    record = await coordinator.receiver.ci_read(spec.code, key)
                except NoReplyError:
                    if asked is not None:
                        raise
                    continue  # a key this model does not have stays silent
                except CodecError as err:
                    raise _error(err) from err
                records.append(_record(coordinator, record))
    except NamesError as err:
        _send_error(connection, msg["id"], err)
        return
    except EiscpError as err:
        _send_error(connection, msg["id"], _error(err))
        return
    connection.send_result(msg["id"], {"code": spec.code, "records": records})


@websocket_command(
    _command(
        WS_CI_SET,
        {
            probatio.Required(ATTR_CODE): str,
            probatio.Optional(ATTR_KEY): _KEY,
            probatio.Required(ATTR_CHANGES): {str: str},
        },
    )
)
@require_admin
@async_response
async def ws_ci_set(hass: HomeAssistant, connection: ActiveConnection, msg: dict[str, Any]) -> None:
    """Change some fields of one record and read it back."""
    try:
        entry = _entry(hass, msg)
        spec = _family(msg[ATTR_CODE])
        coordinator = entry.runtime_data
        async with coordinator.ci_lock:
            try:
                change = await coordinator.receiver.ci_set(
                    spec.code, msg[ATTR_CHANGES], msg.get(ATTR_KEY)
                )
            except CiNotAppliedError as err:
                _keep_baseline(coordinator, err.change)  # part of it may have applied
                raise
            _keep_baseline(coordinator, change)
    except NamesError as err:
        _send_error(connection, msg["id"], err)
        return
    except EiscpError as err:
        _send_error(connection, msg["id"], _error(err))
        return
    except CodecError as err:
        _send_error(connection, msg["id"], _error(err))
        return
    assert change.after is not None  # noqa: S101
    connection.send_result(msg["id"], {"code": spec.code, **_record(coordinator, change.after)})


def _keep_baseline(coordinator: OnkyoCoordinator, change: object) -> None:
    """Remember the old values of a calibration record before its first change."""
    if not isinstance(change, ci.CiChange) or not change.calibration:
        return
    after = change.after
    changed = {
        name: value
        for name, value in change.changes.items()
        if after is None or after.get(name) == value
    }
    saved = coordinator.ci_baseline.get(_baseline_key(change.code, dict(change.key)))
    items = dict(saved.items) if saved is not None else {}
    for name in changed:
        items.setdefault(name, change.before.get(name) or "")
    if items:
        coordinator.ci_baseline[_baseline_key(change.code, dict(change.key))] = ci.CiRecord(
            code=change.code, items=tuple(items.items())
        )


@websocket_command(
    _command(
        WS_CI_RESTORE,
        {
            probatio.Required(ATTR_CODE): str,
            probatio.Optional(ATTR_KEY): _KEY,
            probatio.Optional(ATTR_KEEP): bool,
        },
    )
)
@require_admin
@async_response
async def ws_ci_restore(
    hass: HomeAssistant, connection: ActiveConnection, msg: dict[str, Any]
) -> None:
    """Put a calibration record back, or with ``keep`` forget the saved values."""
    try:
        entry = _entry(hass, msg)
        spec = _family(msg[ATTR_CODE])
        coordinator = entry.runtime_data
        key = dict(msg.get(ATTR_KEY) or {})
        slot = _baseline_key(spec.code, key)
        saved = _saved(coordinator, slot)
        if msg.get(ATTR_KEEP):
            del coordinator.ci_baseline[slot]
            connection.send_result(msg["id"], {"code": spec.code, "key": key, "fields": {}})
            return
        async with coordinator.ci_lock:
            change = ci.CiChange(
                code=spec.code,
                key=key,
                changes=dict(saved.items),
                before=saved,
                set_message="",
                restore_message=ci.encode_set(spec.code, dict(saved.items), key),
                calibration=True,
            )
            after = await coordinator.receiver.ci_restore(change)
            del coordinator.ci_baseline[slot]
    except NamesError as err:
        _send_error(connection, msg["id"], err)
        return
    except (EiscpError, CodecError) as err:
        _send_error(connection, msg["id"], _error(err))
        return
    connection.send_result(msg["id"], {"code": spec.code, **_record(coordinator, after)})
