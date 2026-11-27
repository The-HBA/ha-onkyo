"""Table of known eISCP codes and listening modes (no Home Assistant, no network).

One row per three-letter code the integration reads, writes, or must leave alone. Sources: the
TX-RZ50 survey of 2026-11-26 and 2026-11-27 (sanitized fixture in ``tests/fixtures/tx-rz50``),
the official ISCP sheet v1.34 (2016) and the onkyo-eiscp command list (MIT). Ranges are the ones
measured on the TX-RZ50; a model profile (``lib/profiles``) may narrow the allowed values.

The rules that use these fields (spacing, re-read, availability) live in ``receiver.py``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from collections.abc import Mapping


class Zone(StrEnum):
    """Which part of the receiver a code belongs to."""

    MAIN = "main"
    ZONE2 = "zone2"
    ZONE3 = "zone3"
    SYSTEM = "system"
    """Receiver-wide: identity, network, front display."""


class Kind(StrEnum):
    """What can be done with a code."""

    STATUS = "status"
    """Query only; never set."""
    SETTING = "setting"
    """Query and set."""
    COMMAND = "command"
    """Set only: no query, often no reply (remote keys)."""


class Value(StrEnum):
    """How a parameter is written; ``codecs.py`` decodes and encodes each kind."""

    ENUM = "enum"
    """Fixed parameters, listed in ``Command.options``."""
    HEX = "hex"
    """Unsigned hex level, for example volume ``7C``."""
    SIGNED_HEX = "signed_hex"
    """Sign plus hex steps: ``-0A``, ``000``, ``+18``."""
    SIGNED_DEC = "signed_dec"
    """Sign plus decimal: ``+005``; zero reads ``0000``."""
    TONE = "tone"
    """Bass and treble pair ``B-2T00``; a set writes one side, ``B+1``."""
    SLOTS = "slots"
    """One digit per Dirac slot (2 active, 1 filled, 0 empty); written as ``C0n``."""
    SLEEP = "sleep"
    """``OFF`` or hex minutes."""
    TEXT = "text"
    """Comma separated fields or free text."""
    HEX_TEXT = "hex_text"
    """Text sent as hex ASCII (front display)."""
    XML = "xml"
    """An XML document (receiver information)."""


class Reply(StrEnum):
    """How the receiver answers a set."""

    ECHO = "echo"
    """With the new value, or ``N/A`` when refused."""
    READ_BACK = "read_back"
    """Only on its own display; a query confirms the change."""
    NONE = "none"
    """Not at all."""


@dataclass(frozen=True, slots=True, kw_only=True)
class Command:
    """One known code."""

    code: str
    zone: Zone
    kind: Kind
    value: Value
    options: Mapping[str, str] = field(default_factory=dict)
    """Parameter to option key (``ENUM`` codes); option keys are translation keys."""
    minimum: float | None = None
    maximum: float | None = None
    step: float | None = None
    """Size of one raw step in ``unit``."""
    unit: str = ""
    reply: Reply = Reply.ECHO
    context: bool = False
    """A change of this code changes what other settings allow or hold."""
    reread: bool = False
    """Read again after a context change: the value or its availability depends on it."""
    standby_silent: bool = False
    """Silent while the receiver is in standby; counts as supported then."""
    pushed: bool = True
    """Changes arrive as pushes; False means the value must be polled."""
    never_query: bool = False
    """Querying it has a side effect on the receiver."""
    never_set: bool = False
    """Setting it has a side effect, or it is a status."""
    note: str = ""


ON_OFF: Final[Mapping[str, str]] = MappingProxyType({"00": "off", "01": "on"})


def _rows(*commands: Command) -> Mapping[str, Command]:
    return MappingProxyType({command.code: command for command in commands})


COMMANDS: Final[Mapping[str, Command]] = _rows(
    # Main zone: power, volume, input, listening mode.
    Command(
        code="PWR",
        zone=Zone.MAIN,
        kind=Kind.SETTING,
        value=Value.ENUM,
        options={"00": "standby", "01": "on"},
        context=True,
        note="Power-on sets MVL to 7C and needs about 20 s before queries answer again.",
    ),
    Command(
        code="MVL",
        zone=Zone.MAIN,
        kind=Kind.SETTING,
        value=Value.HEX,
        minimum=0,
        maximum=200,
        step=0.5,
        unit="dB",
        note="Raw 00 to the NRI maximum; dB = raw / 2 - 82 on 0.5 dB models.",
    ),
    Command(
        code="AMT",
        zone=Zone.MAIN,
        kind=Kind.SETTING,
        value=Value.ENUM,
        options=ON_OFF,
        note="Power-off clears mute.",
    ),
    Command(
        code="SLI",
        zone=Zone.MAIN,
        kind=Kind.SETTING,
        value=Value.ENUM,
        context=True,
        note="Inputs come from NRI; SLI80 is zone 2 and 3 only.",
    ),
    Command(
        code="LMD",
        zone=Zone.MAIN,
        kind=Kind.SETTING,
        value=Value.ENUM,
        context=True,
        reread=True,
        note="See LISTENING_MODES. N/A in standby; a set within 3 s of a mode change is ignored.",
    ),
    # Dirac Live (RULES.md 13: slot choice only).
    Command(
        code="DSS",
        zone=Zone.MAIN,
        kind=Kind.SETTING,
        value=Value.SLOTS,
        context=True,
        note="Reads DSS112 (slot 3 active); written as DSSC00 (off) to DSSC03.",
    ),
    # Tone and levels.
    Command(
        code="TFR",
        zone=Zone.MAIN,
        kind=Kind.SETTING,
        value=Value.TONE,
        minimum=-10,
        maximum=10,
        step=1,
        unit="dB",
        reread=True,
    ),
    Command(
        code="SWL",
        zone=Zone.MAIN,
        kind=Kind.SETTING,
        value=Value.SIGNED_HEX,
        minimum=-15,
        maximum=12,
        step=0.5,
        unit="dB",
        reread=True,
        note="Stored per input. Zero assumed to read 000, not yet seen.",
    ),
    Command(
        code="SW2",
        zone=Zone.MAIN,
        kind=Kind.SETTING,
        value=Value.SIGNED_HEX,
        minimum=-15,
        maximum=12,
        step=0.5,
        unit="dB",
        reread=True,
        note="N/A on the TX-RZ50 with one subwoofer.",
    ),
    Command(
        code="CTL",
        zone=Zone.MAIN,
        kind=Kind.SETTING,
        value=Value.SIGNED_HEX,
        minimum=-12,
        maximum=12,
        step=0.5,
        unit="dB",
        reread=True,
        note="Refused without a centre speaker.",
    ),
    Command(
        code="VOC",
        zone=Zone.MAIN,
        kind=Kind.SETTING,
        value=Value.HEX,
        minimum=0,
        maximum=5,
        step=1,
        reread=True,
        note="Vocal enhancer; refused in All Ch Stereo; VOC06 sets 00.",
    ),
    Command(
        code="DLC",
        zone=Zone.MAIN,
        kind=Kind.SETTING,
        value=Value.HEX,
        minimum=0,
        maximum=6,
        step=1,
        reread=True,
        standby_silent=True,
        note="Dialog level; reads 00 on the TX-RZ50, sets refused.",
    ),
    Command(
        code="AVS",
        zone=Zone.MAIN,
        kind=Kind.SETTING,
        value=Value.SIGNED_DEC,
        minimum=-100,
        maximum=500,
        step=5,
        unit="ms",
    ),
    # Sound settings.
    Command(
        code="MOT",
        zone=Zone.MAIN,
        kind=Kind.SETTING,
        value=Value.ENUM,
        options=ON_OFF,
        reread=True,
        note="Music Optimizer; refused outside Stereo on the TX-RZ50.",
    ),
    Command(code="RAS", zone=Zone.MAIN, kind=Kind.SETTING, value=Value.ENUM, options=ON_OFF),
    Command(
        code="LTN",
        zone=Zone.MAIN,
        kind=Kind.SETTING,
        value=Value.ENUM,
        options={"00": "off", "01": "low", "02": "high", "03": "auto"},
        reread=True,
    ),
    Command(
        code="EQS",
        zone=Zone.MAIN,
        kind=Kind.SETTING,
        value=Value.ENUM,
        options={"00": "off", "01": "preset_1", "02": "preset_2", "03": "preset_3"},
        standby_silent=True,
    ),
    Command(
        code="DGF",
        zone=Zone.MAIN,
        kind=Kind.SETTING,
        value=Value.ENUM,
        options={"00": "slow", "01": "sharp", "02": "short", "03": "auto"},
        note="DGF02 is ignored on the TX-RZ50 (the reply echoes the old value).",
    ),
    Command(
        code="SLP",
        zone=Zone.MAIN,
        kind=Kind.SETTING,
        value=Value.SLEEP,
        minimum=0,
        maximum=90,
        step=1,
        unit="min",
    ),
    Command(
        code="DIM",
        zone=Zone.SYSTEM,
        kind=Kind.SETTING,
        value=Value.ENUM,
        options={"00": "bright", "01": "dim", "02": "dark", "03": "off", "08": "bright_led_off"},
    ),
    Command(
        code="HDO",
        zone=Zone.MAIN,
        kind=Kind.SETTING,
        value=Value.ENUM,
        options={
            "00": "off",
            "01": "main",
            "02": "sub",
            "03": "both",
            "04": "both_main",
            "05": "both_sub",
        },
        note="Never written in the survey; can blank the screen.",
    ),
    # Information.
    Command(
        code="IFA",
        zone=Zone.MAIN,
        kind=Kind.STATUS,
        value=Value.TEXT,
        reread=True,
        note="Audio input; N/A in standby and briefly after a Dirac change.",
    ),
    Command(code="IFV", zone=Zone.MAIN, kind=Kind.STATUS, value=Value.TEXT, reread=True),
    Command(code="FLD", zone=Zone.SYSTEM, kind=Kind.STATUS, value=Value.HEX_TEXT),
    Command(
        code="TPD",
        zone=Zone.SYSTEM,
        kind=Kind.STATUS,
        value=Value.TEXT,
        pushed=False,
        note="Temperature, for example 'F 86C 30'.",
    ),
    Command(code="NRI", zone=Zone.SYSTEM, kind=Kind.STATUS, value=Value.XML),
    Command(code="FWV", zone=Zone.SYSTEM, kind=Kind.STATUS, value=Value.TEXT),
    # Remote keys.
    Command(
        code="OSD",
        zone=Zone.MAIN,
        kind=Kind.COMMAND,
        value=Value.ENUM,
        options={
            "UP": "up",
            "DOWN": "down",
            "LEFT": "left",
            "RIGHT": "right",
            "ENTER": "enter",
            "EXIT": "exit",
            "MENU": "menu",
            "HOME": "home",
            "QUICK": "quick",
            "AUDIO": "audio",
            "VIDEO": "video",
        },
        reply=Reply.NONE,
    ),
    # Zone 2.
    Command(
        code="ZPW",
        zone=Zone.ZONE2,
        kind=Kind.SETTING,
        value=Value.ENUM,
        options={"00": "standby", "01": "on"},
    ),
    Command(
        code="ZVL",
        zone=Zone.ZONE2,
        kind=Kind.SETTING,
        value=Value.HEX,
        minimum=0,
        maximum=200,
        step=0.5,
        unit="dB",
        note="N/A while zone 2 is on at a fixed output level (TX-RZ50).",
    ),
    Command(code="ZMT", zone=Zone.ZONE2, kind=Kind.SETTING, value=Value.ENUM, options=ON_OFF),
    Command(code="SLZ", zone=Zone.ZONE2, kind=Kind.SETTING, value=Value.ENUM),
    # Zone 3.
    Command(
        code="PW3",
        zone=Zone.ZONE3,
        kind=Kind.SETTING,
        value=Value.ENUM,
        options={"00": "standby", "01": "on"},
        note="Power-on refused on the TX-RZ50 (pushes PW300 and MRM44).",
    ),
    Command(
        code="VL3",
        zone=Zone.ZONE3,
        kind=Kind.SETTING,
        value=Value.HEX,
        minimum=0,
        maximum=200,
        step=0.5,
        unit="dB",
    ),
    Command(code="MT3", zone=Zone.ZONE3, kind=Kind.SETTING, value=Value.ENUM, options=ON_OFF),
    Command(code="SL3", zone=Zone.ZONE3, kind=Kind.SETTING, value=Value.ENUM),
    # Leave alone: side effects, popups or status only.
    Command(
        code="SAM",
        zone=Zone.MAIN,
        kind=Kind.STATUS,
        value=Value.TEXT,
        never_set=True,
        note="SAMFR, even as the same value, switched LMD to Stereo.",
    ),
    Command(
        code="NSB",
        zone=Zone.SYSTEM,
        kind=Kind.STATUS,
        value=Value.TEXT,
        never_set=True,
        note="Network standby; OFF would cut the connection in standby.",
    ),
    Command(
        code="MRM",
        zone=Zone.SYSTEM,
        kind=Kind.STATUS,
        value=Value.TEXT,
        never_set=True,
        note="Status; stuck at 44 after zone 3 refused power-on.",
    ),
    Command(code="TGA", zone=Zone.SYSTEM, kind=Kind.STATUS, value=Value.TEXT, never_set=True),
    Command(
        code="NLT",
        zone=Zone.SYSTEM,
        kind=Kind.STATUS,
        value=Value.TEXT,
        never_query=True,
        never_set=True,
        note="Querying pushes a NET popup.",
    ),
    Command(
        code="NCP",
        zone=Zone.SYSTEM,
        kind=Kind.STATUS,
        value=Value.TEXT,
        never_query=True,
        never_set=True,
        note="NET popup XML; querying shows a popup.",
    ),
)


class ModeGroup(StrEnum):
    """Groups for the card's listening mode picker."""

    STEREO = "stereo"
    SURROUND = "surround"
    THX = "thx"
    DSP = "dsp"
    """Onkyo's sound fields (Orchestra, Game-RPG and similar)."""
    OTHER = "other"


@dataclass(frozen=True, slots=True)
class ListeningMode:
    """One listening mode code with its clean, unique name (RULES.md 14)."""

    code: str
    name: str
    group: ModeGroup


def _modes(*rows: tuple[str, str, ModeGroup]) -> Mapping[str, ListeningMode]:
    return MappingProxyType({code: ListeningMode(code, name, group) for code, name, group in rows})


_S, _R, _T, _D, _O = (
    ModeGroup.STEREO,
    ModeGroup.SURROUND,
    ModeGroup.THX,
    ModeGroup.DSP,
    ModeGroup.OTHER,
)

LISTENING_MODES: Final[Mapping[str, ListeningMode]] = _modes(
    # Seen on the TX-RZ50 (names as its display and IFA show them, made unique).
    ("00", "Stereo", _S),
    ("01", "Direct", _S),
    ("11", "Pure Audio", _S),
    ("0C", "All Ch Stereo", _S),
    ("0F", "Mono", _S),
    ("13", "Mono Music", _S),
    ("80", "Dolby Surround", _R),
    ("82", "DTS Neural:X", _R),
    ("40", "Straight Decode", _R),
    ("84", "THX Cinema (Dolby Surround)", _T),
    ("85", "THX Cinema (Neural:X)", _T),
    ("8B", "THX Music (Dolby Surround)", _T),
    ("8C", "THX Music (Neural:X)", _T),
    ("89", "THX Games (Dolby Surround)", _T),
    ("8A", "THX Games (Neural:X)", _T),
    ("08", "Orchestra", _D),
    ("09", "Unplugged", _D),
    ("0A", "Studio-Mix", _D),
    ("0B", "TV Logic", _D),
    ("0D", "Theater-Dimensional", _D),
    ("03", "Game-RPG", _D),
    ("05", "Game-Action", _D),
    ("06", "Game-Rock", _D),
    ("0E", "Game-Sports", _D),
    # Other models (official sheet v1.34 and onkyo-eiscp), not seen on the TX-RZ50.
    ("02", "Surround", _R),
    ("04", "THX", _T),
    ("07", "Mono Movie", _O),
    ("12", "Multiplex", _O),
    ("14", "Dolby Virtual", _R),
    ("15", "DTS Surround Sensation", _R),
    ("16", "Audyssey DSX", _R),
    ("41", "Dolby EX", _R),
    ("42", "THX Cinema", _T),
    ("43", "THX Surround EX", _T),
    ("44", "THX Music", _T),
    ("45", "THX Games", _T),
    ("50", "THX Ultra2 Cinema", _T),
    ("51", "THX Ultra2 Music", _T),
    ("52", "THX Ultra2 Games", _T),
    ("81", "Dolby Pro Logic II Music", _R),
    ("83", "DTS Neo:6 Music", _R),
    ("86", "Dolby Pro Logic II Game", _R),
    ("87", "Neural Surround", _R),
    ("88", "Neural THX", _T),
    ("8D", "Neural THX Cinema", _T),
    ("8E", "Neural THX Music", _T),
    ("8F", "Neural THX Games", _T),
    ("90", "Dolby Pro Logic IIz Height", _R),
    ("93", "Neural Digital Music", _R),
    ("9A", "DTS Neo:X Game", _R),
    ("FF", "Auto Surround", _O),
)

NEVER_OFFER_MODES: Final = frozenset({"1F"})
"""Whole House Mode: powers zone 2 on; the main zone's LMD then reads N/A."""

DIRAC_SLOTS: Final[Mapping[str, str]] = MappingProxyType(
    {"C00": "off", "C01": "slot_1", "C02": "slot_2", "C03": "slot_3"}
)
"""Dirac write parameter to option key; ``DSS`` reads one digit per slot."""
