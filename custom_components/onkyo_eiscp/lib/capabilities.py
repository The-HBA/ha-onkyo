"""What one receiver supports: NRI plus a probe of every known code.

``probe(client)`` reads ``NRI`` (model, MAC, zones, inputs, volume range), then sends every
queryable code of ``commands.COMMANDS`` at 10 ms spacing and waits 2 s for the answers (the
33,696 code sweep of the survey proved this safe). A code that stays silent is unsupported.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from types import MappingProxyType
from typing import TYPE_CHECKING, Final

from .codecs import DeviceInfo, parse_device_info
from .commands import COMMANDS, LISTENING_MODES, NEVER_OFFER_MODES, Kind, Value
from .profiles import find_profile

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

    from .client import EiscpClient
    from .frame import Message

NOT_AVAILABLE = "N/A"
NRI_TIMEOUT = 8.0
PROBE_SPACING = 0.01
PROBE_SETTLE = 2.0


@dataclass(frozen=True, slots=True)
class ZoneInfo:
    """One enabled zone from NRI."""

    id: str
    """``main``, ``zone2`` or ``zone3``."""
    name: str
    volume_max: int
    """Raw volume at the top: ``volmax * 2`` on 0.5 dB models (``volstep`` 0), else ``volmax``."""
    half_db: bool
    """True when one raw volume step is 0.5 dB (dB = raw / 2 - 82)."""


@dataclass(frozen=True, slots=True)
class InputInfo:
    """One input from NRI, with the receiver's own name."""

    code: str
    """The ``SLI`` parameter, upper case."""
    name: str
    zones: frozenset[str]
    """The zones that can select it."""


@dataclass(frozen=True, slots=True)
class Capabilities:
    """The result of a probe; the integration builds its entities from it."""

    model: str
    brand: str
    mac: str
    firmware: str
    zones: tuple[ZoneInfo, ...]
    inputs: tuple[InputInfo, ...]
    supported: frozenset[str]
    """Codes that answered a value or ``N/A`` (and, in standby, the ``standby_silent`` codes)."""
    listening_modes: tuple[str, ...]
    signal_modes: Mapping[str, tuple[str, ...]]
    options: Mapping[str, tuple[str, ...]]
    """Allowed set parameters per enum code."""
    values: Mapping[str, str]
    """The probe's answers (``N/A`` included)."""

    def zone(self, zone_id: str) -> ZoneInfo | None:
        """Return the zone with this id, if enabled."""
        return next((zone for zone in self.zones if zone.id == zone_id), None)


def queryable_codes() -> tuple[str, ...]:
    """Every known code that is safe to query (not ``never_query``, not command only)."""
    return tuple(
        code
        for code, command in COMMANDS.items()
        if not command.never_query and command.kind is not Kind.COMMAND
    )


async def read_codes(
    client: EiscpClient,
    codes: Iterable[str],
    *,
    spacing: float = PROBE_SPACING,
    settle: float = PROBE_SETTLE,
) -> dict[str, str]:
    """Send ``<code>QSTN`` for each code at ``spacing`` and collect the answers for ``settle`` s.

    Silent codes are missing from the result. Pushes of the same codes count as answers.
    """
    ordered = list(dict.fromkeys(codes))
    wanted = set(ordered)
    answers: dict[str, str] = {}

    def collect(message: Message) -> None:
        if message.code in wanted:
            answers[message.code] = message.param

    remove = client.add_listener(collect)
    try:
        for code in ordered:
            await client.send(f"{code}QSTN")
            await asyncio.sleep(spacing)
        await asyncio.sleep(settle)
    finally:
        remove()
    return answers


def _zones(info: DeviceInfo) -> tuple[ZoneInfo, ...]:
    zones: list[ZoneInfo] = []
    for zone in info.zones:
        if not zone.enabled or zone.id not in {"main", "zone2", "zone3"}:
            continue
        half = zone.volume_step == 0
        zones.append(
            ZoneInfo(
                id=zone.id,
                name=zone.name,
                volume_max=zone.volume_max * 2 if half else zone.volume_max,
                half_db=half,
            )
        )
    return tuple(zones)


def supported_codes(answers: Mapping[str, str]) -> frozenset[str]:
    """Codes that answered, plus (in standby) the codes that are silent then."""
    supported = set(answers)
    if answers.get("PWR") == "00":
        supported.update(code for code, command in COMMANDS.items() if command.standby_silent)
    return frozenset(supported)


#: OSD keys that NRI switches off with a control of value "0" (a missing control keeps the key).
_OSD_CONTROLS: Final = {
    "HOME": ("Home",),
    "QUICK": ("Quick",),
    "UP": ("Cursor",),
    "DOWN": ("Cursor",),
    "LEFT": ("Cursor",),
    "RIGHT": ("Cursor",),
    "ENTER": ("Cursor",),
    # MENU is the Setup key; the Menu control alone does not turn it off (survey session 21).
    "MENU": ("Setup", "Menu"),
}


def _osd_keys(keys: tuple[str, ...], controls: Mapping[str, str]) -> tuple[str, ...]:
    """Drop the remote keys NRI says the model does not have."""

    def kept(key: str) -> bool:
        names = [name for name in _OSD_CONTROLS.get(key, ()) if name in controls]
        return not names or any(controls[name] != "0" for name in names)

    return tuple(key for key in keys if kept(key))


def build(info: DeviceInfo, answers: Mapping[str, str]) -> Capabilities:
    """Combine NRI and the probe's answers into ``Capabilities``."""
    profile = find_profile(info.model)
    default_modes = tuple(code for code in LISTENING_MODES if code not in NEVER_OFFER_MODES)
    options = {
        code: tuple(command.options)
        for code, command in COMMANDS.items()
        if command.value is Value.ENUM and command.options
    }
    if profile is not None:
        options.update(profile.options)
    if "OSD" in options:
        options["OSD"] = _osd_keys(options["OSD"], info.controls)
    return Capabilities(
        model=info.model,
        brand=info.brand,
        mac=info.mac,
        firmware=info.firmware,
        zones=_zones(info),
        inputs=tuple(
            InputInfo(code=item.code, name=item.name, zones=item.zones)
            for item in info.inputs
            if item.enabled
        ),
        supported=supported_codes(answers),
        listening_modes=default_modes if profile is None else profile.listening_modes,
        signal_modes=MappingProxyType({} if profile is None else dict(profile.signal_modes)),
        options=MappingProxyType(options),
        values=MappingProxyType(dict(answers)),
    )


async def probe(
    client: EiscpClient, *, spacing: float = PROBE_SPACING, settle: float = PROBE_SETTLE
) -> Capabilities:
    """Read NRI, then every queryable code; return what this receiver supports."""
    info = parse_device_info(await client.query("NRI", timeout=NRI_TIMEOUT))
    codes = [code for code in queryable_codes() if code != "NRI"]
    answers = await read_codes(client, codes, spacing=spacing, settle=settle)
    return build(info, answers)
