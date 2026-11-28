"""CI (custom install) config commands: decode a record, encode a partial set (no Home Assistant).

The receiver's config settings (input assign, speaker levels, equalizer and so on) travel over
the normal eISCP connection with a lower-case ``s`` in front of a three letter code that ends in
``C`` (``sLCC`` is the channel level family). A record is a run of fields, each two letters for
the name followed by a value of fixed width (three characters, a few families differ):

    sLCCMMMM1FL+07CT000FR+09 ...   key MM = MM1, then FL = +07, CT = 000, FR = +09

Read: ``s<CODE>QSTN`` plus the key fields (``sLCCQSTNMMMM1``). Set: ``s<CODE>`` plus the key
fields plus only the fields that change (``sLCCMMMM1SW-29``). A set gets no reply, so the caller
reads the record back (``Receiver.ci_set`` does). Specs: project-soul/specs/web-setup-backup.md.

Guards: ``CFC`` (speaker layout), ``NTC`` and ``N2C`` (network) and the other families the
receiver ignores or that could lock us out are read-only, and ``encode_set`` refuses them.
``plan_set`` records the old values and returns the command that puts them back.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from itertools import product
from typing import TYPE_CHECKING, Final

from .exceptions import CiRefusedError, CodecError

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator, Mapping

PREFIX: Final = "s"
QUERY: Final = "QSTN"
NAME_LENGTH: Final = 2
CODE_LENGTH: Final = 3
DEFAULT_WIDTH: Final = 3

SELECTORS: Final = ("BD", "GAM", "CBL", "STB", "PC", "AUX", "CD", "TV", "PHO", "TUN", "NET", "BLT")
"""Selector keys (``SL`` field) of the TX-RZ50, padded to three characters on the wire."""
SHORT_KEYS: Final = ("BD", "CB", "GM", "ST", "PC", "AX", "CD", "TV", "PH", "TN", "NT", "BT")
"""Field names inside the HIC, VIC, DIC, AAC and ISC records, one per selector."""
PRESETS: Final = ("OFF", "MM1", "MM2", "MM3")
"""Preset keys (``MM`` field): Dirac off and Dirac slots 1 to 3."""
EQ_CHANNELS: Final = ("FRT", "CTR", "HI1", "HI2", "SUR", "SBK", "SWF")
EQ_BANDS: Final = tuple("B" + band for band in "123456789ABCDEF")

CALIBRATION: Final = frozenset({"LCC", "SDC", "COC"})
"""Families that hold the Dirac calibration: write with ``plan_set`` and restore afterwards."""

_NUM = r"\d{3}"
_BIT = r"00[01]"
_SIGNED = r"000|[+-]\d{2}"
_NEGATIVE = r"000|-\d{2}"
_TEXT = r"[ -~]*"


@dataclass(frozen=True, slots=True)
class FieldSpec:
    """One field of a family: its width, the values it accepts and whether we may set it."""

    width: int = DEFAULT_WIDTH
    pattern: str | None = None
    """Regular expression the whole value must match; ``None`` accepts any value of the width."""
    writable: bool = True
    pad: bool = False
    """Text shorter than the width is padded with spaces (names)."""

    def normalise(self, value: str) -> str:
        """Return ``value`` ready for the wire, or raise ``CodecError``."""
        if self.pad:
            value = value.ljust(self.width)
        if len(value) != self.width or (
            self.pattern is not None and re.fullmatch(self.pattern, value) is None
        ):
            msg = f"invalid value {value!r} (width {self.width}, pattern {self.pattern})"
            raise CodecError(msg)
        return value


@dataclass(frozen=True, slots=True)
class KeyDef:
    """A key field (selector, preset, channel ...) that says which record a message is about."""

    name: str
    values: tuple[str, ...] = ()
    """The values to enumerate; others are still sent if they look like a key."""


@dataclass(frozen=True, slots=True)
class FamilySpec:
    """One CI family."""

    code: str
    title: str
    fields: Mapping[str, FieldSpec]
    key: tuple[KeyDef, ...] = ()
    shared: frozenset[str] = frozenset()
    """Global fields: one value for the whole family, repeated in every record of it."""
    calibration: bool = False
    query: str | None = None
    """The code to ask with when it differs from the family code (``MN-`` for ``MNC``)."""
    reason: str = ""
    """Why the family is read-only; empty when at least one field can be set."""

    @property
    def writable(self) -> bool:
        """True when at least one field may be set."""
        return any(spec.writable for spec in self.fields.values())

    @property
    def key_names(self) -> tuple[str, ...]:
        """The names of the key fields, in wire order."""
        return tuple(item.name for item in self.key)

    def width(self, name: str) -> int:
        """Return the value width of field ``name``."""
        spec = self.fields.get(name)
        return spec.width if spec is not None else DEFAULT_WIDTH

    def all_keys(self) -> Iterator[dict[str, str]]:
        """Every key combination to read this family completely (one empty dict if no key)."""
        if not self.key:
            yield {}
            return
        for combo in product(*(item.values for item in self.key)):
            yield dict(zip(self.key_names, combo, strict=True))


def _fields(
    names: str,
    pattern: str | None = _NUM,
    *,
    width: int = DEFAULT_WIDTH,
    writable: bool = True,
    pad: bool = False,
) -> dict[str, FieldSpec]:
    return {
        name: FieldSpec(width=width, pattern=pattern, writable=writable, pad=pad)
        for name in names.split()
    }


def _family(  # noqa: PLR0913
    code: str,
    title: str,
    *fields: dict[str, FieldSpec],
    key: tuple[KeyDef, ...] = (),
    shared: str = "",
    calibration: bool = False,
    query: str | None = None,
    reason: str = "",
) -> FamilySpec:
    merged: dict[str, FieldSpec] = {}
    for part in fields:
        merged.update(part)
    return FamilySpec(
        code=code,
        title=title,
        fields=merged,
        key=key,
        shared=frozenset(shared.split()),
        calibration=calibration,
        query=query,
        reason=reason,
    )


def _read_only(
    names: str, pattern: str | None = None, *, width: int = DEFAULT_WIDTH
) -> dict[str, FieldSpec]:
    return _fields(names, pattern, width=width, writable=False)


_SL = (KeyDef("SL", SELECTORS),)
_MM = KeyDef("MM", PRESETS)
_SPEAKERS = "FL CT FR HL HR 2L 2R SR BR BL SL SW S2"
_INPUT_PORTS = "BD CB GM ST PC CD TV PH"

FAMILIES: Final[Mapping[str, FamilySpec]] = {
    spec.code: spec
    for spec in (
        _family(
            "NMC",
            "Input names",
            _fields("NM", _TEXT, width=13, pad=True),
            key=(KeyDef("SL", tuple(s for s in SELECTORS if s not in {"NET", "BLT"})),),
        ),
        _family(
            "SLC",
            "Audio source per input",
            _fields("AS", r"HDM|ANA|ARC|DIG"),
            _read_only("FX VS", r"[A-Z]{3}"),
            key=_SL,
        ),
        _family("HIC", "HDMI input assign", _fields(_INPUT_PORTS, r"NON|HI\d")),
        _family("VIC", "Video input assign", _fields(_INPUT_PORTS, r"NON|[A-Z]{2}\d|[A-Z]\dN")),
        _family("DIC", "Digital audio input assign", _fields(_INPUT_PORTS, r"NON|[CO]\dN")),
        _family("AAC", "Analog audio input assign", _fields(_INPUT_PORTS, r"NON|AI\d|PHO")),
        _family("ISC", "Input skip", _fields(" ".join(SHORT_KEYS), _BIT)),
        _family(
            "TOC",
            "TV out and OSD",
            _fields("HO DV US SR ZH OD MO SS HS"),
            _fields("LG", r"[A-Z]{3}"),
            key=_SL,
            shared="HO DV US SR ZH LG OD MO SS",
        ),
        _family("IVC", "Per-input volume", _fields("IV", r"LST|\d{3}"), key=_SL),
        _family(
            "AKC",
            "Per-input audio",
            _fields("BF VC TF S1 S2 S3 RE RT LN E1 IM DL AE EQ AS MO DF"),
            _fields("SA", r"[A-Z]{3}"),
            key=_SL,
            shared="BF VC TF S1 S2 S3 RE RT LN SA E1 IM",
        ),
        _family(
            "HLC",
            "Per-input HDMI",
            _fields("EA HD HP DV DC 3D DS VR FV AM AL FR SB"),
            key=_SL,
            shared="EA",
        ),
        _family(
            "VLC",
            "Volume",
            _fields("VD", r"REL|ABS"),
            _fields("MV PV HP", r"OFF|LST|\d{3}"),
            _read_only("ML"),
        ),
        _family(
            "APC",
            "Auto standby and power",
            _fields("ST AP HT PO WU"),
            _read_only("NS"),  # network standby: a wrong value could cut Home Assistant off
        ),
        _family(
            "HDC",
            "HDMI (CEC, ARC, standby through)",
            _fields("CE AR AO PQ LS"),
            _fields("HT", r"AUT|\d{3}"),
        ),
        _family(
            "EQC",
            "Manual equalizer",
            _fields(" ".join(EQ_BANDS), _SIGNED),
            key=(
                KeyDef("PS", ("001", "002", "003")),
                KeyDef("CH", EQ_CHANNELS),
            ),
        ),
        _family("SWC", "Subwoofer equalizer", _fields("F1 F2 F3"), _fields("L1 L2 L3", _NEGATIVE)),
        _family("SCC", "Speaker connection", _fields("BR FR CT H1 H2 SR SB SW")),
        _family(
            "MZC",
            "Multi-zone",
            _fields("ZO MV PV", r"OFF|LST|\d{3}"),
            key=(KeyDef("ZN", ("002", "003")),),
        ),
        _family(
            "LCC",
            "Channel levels (0.1 dB)",
            _fields(_SPEAKERS, _SIGNED),
            key=(_MM,),
            calibration=True,
        ),
        _family(
            "SDC",
            "Speaker distances",
            _fields(_SPEAKERS),
            _read_only("UN", r"MTR|FTS"),
            key=(_MM,),
            shared="UN",
            calibration=True,
        ),
        _family(
            "COC",
            "Crossover",
            _fields("FR CT H1 H2 SR SB LF", r"NON|OFF|\d{3}"),
            _read_only("DB XT DL"),
            key=(_MM, KeyDef("XM", ("IND", "DBC"))),
            shared="DB",
            calibration=True,
        ),
        _family("DSC", "Dirac and audio options", _fields("DC AR")),
        _family("TXC", "Text and display options", _fields("SS TS BG LP")),
        _family("SVC", "Service option", _fields("SV")),
        _family("MMC", "Music Optimizer options", _fields("MI"), _read_only("XI MO")),
        _family("DLC", "Display and lock options", _fields("LM CS")),
        _family("DTC", "Digital options", _fields("AS IM IU IB"), _read_only("DC IV")),
        _family("BTC", "Bluetooth", _fields("BR DC AR BT UA LL OL")),
        _family(
            "TGC",
            "12 V triggers",
            _fields("ZN DL " + " ".join(SHORT_KEYS)),
        ),
        _family("PZC", "Power zone option", _fields("PZ")),
        _family("RMC", "Remote ID", _fields("ID")),
        _family("UDC", "Option UD", _fields("UN")),
        _family(
            "WSC",
            "Option WS",
            _fields("OZ"),
            _read_only("IS V2 V3", r"[A-Z]{3}|\d{3}"),
            _read_only("VM", r"[A-Z]{3}"),
            _read_only("CD", width=68),
            key=(KeyDef("SO", ("000", "001", "002")),),
        ),
        _family(
            "CFC",
            "Speaker layout",
            _read_only("SC SW H1 H2 ZS ZP SB BA IM"),
            reason="the receiver ignores layout writes and a wrong layout breaks the calibration",
        ),
        _family(
            "LLC",
            "Option LL",
            _read_only("LL"),
            reason="the receiver ignores writes",
        ),
        _family("TNC", "Tuner step", _read_only("FS"), reason="the receiver ignores writes"),
        _family(
            "LKC",
            "Lock",
            _read_only("LK KY IR"),
            reason="a lock could block the restore (never tested on purpose)",
        ),
        _family(
            "NTC",
            "Network",
            _read_only("NT DH"),
            _read_only("MA", width=13),
            _read_only("IP SN GW DS", width=8),
            _read_only("PU", width=128),
            _read_only("PP", width=8),
            reason="a wrong network setting could cut the receiver off (DECISIONS 14)",
        ),
        _family(
            "N2C",
            "Network name",
            _read_only("FN AP AN", width=33),
            _read_only("AS"),
            reason="network names are read-only (DECISIONS 14)",
        ),
        _family(
            "MNC",
            "Model information",
            _read_only("MN", width=13),
            _read_only("CN RN", width=18),
            _read_only("RQ DI DB DU IM UD SC AP IX DH DL MV"),
            query="MN-",
            reason="status only",
        ),
        _family(
            "ST-",
            "Live state (decimal)",
            _read_only("PM P2 P3 VL V2 V3 MT M2 M3 LM TG"),
            _read_only("SL S2 S3"),
            reason="status only",
        ),
        _family("AM-", "Tuner state", _read_only("PR T1 FN"), reason="status only"),
    )
}
"""Every family the library knows. Unknown families still decode with the default width."""

EXPOSED: Final = tuple(code for code, spec in FAMILIES.items() if spec.writable)
"""The families with at least one settable field, in a stable order."""


# ----- records -------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class CiRecord:
    """One decoded record: the family code and its fields in wire order."""

    code: str
    items: tuple[tuple[str, str], ...]

    @property
    def spec(self) -> FamilySpec | None:
        """The family spec, or ``None`` for a family we do not know."""
        return FAMILIES.get(self.code)

    def get(self, name: str, default: str | None = None) -> str | None:
        """Return the raw value of field ``name`` (padding kept), or ``default``."""
        for item, value in self.items:
            if item == name:
                return value
        return default

    @property
    def key(self) -> dict[str, str]:
        """The key fields (selector, preset ...), values without padding."""
        names = self.spec.key_names if self.spec is not None else ()
        return {name: value.strip() for name, value in self.items if name in names}

    @property
    def fields(self) -> dict[str, str]:
        """Every field that is not a key, raw values."""
        names = self.spec.key_names if self.spec is not None else ()
        return {name: value for name, value in self.items if name not in names}

    def encode(self) -> str:
        """Return the record as the receiver sends it, ``s`` and code included."""
        return PREFIX + self.code + "".join(name + value for name, value in self.items)


def decode(message: str) -> CiRecord:
    """Decode ``message`` (``sLCCMMMM1FL+07...``, with the leading ``s``) into a record."""
    if not message.startswith(PREFIX) or len(message) < 1 + CODE_LENGTH:
        msg = f"not a CI record: {message!r}"
        raise CodecError(msg)
    code = message[1 : 1 + CODE_LENGTH]
    return CiRecord(code=code, items=tokens(code, message[1 + CODE_LENGTH :]))


def tokens(code: str, text: str) -> tuple[tuple[str, str], ...]:
    """Split the field run ``text`` of family ``code`` into (name, value) pairs.

    The last value may be shorter than its width (a receiver that trims trailing spaces).
    """
    spec = FAMILIES.get(code)
    items: list[tuple[str, str]] = []
    pos = 0
    while pos < len(text):
        name = text[pos : pos + NAME_LENGTH]
        width = spec.width(name) if spec is not None else DEFAULT_WIDTH
        value = text[pos + NAME_LENGTH : pos + NAME_LENGTH + width]
        if len(name) < NAME_LENGTH or not value:
            msg = f"CI {code}: broken field at {pos} in {text!r}"
            raise CodecError(msg)
        items.append((name, value))
        pos += NAME_LENGTH + width
    return tuple(items)


# ----- formatting helpers --------------------------------------------------------------------


def format_signed(value: int) -> str:
    """Format a signed level in the receiver's way: ``000``, ``+07``, ``-30`` (tenths of a dB)."""
    if not -99 <= value <= 99:  # noqa: PLR2004
        msg = f"level {value} out of range"
        raise CodecError(msg)
    return "000" if value == 0 else f"{value:+03d}"


def parse_signed(text: str) -> int:
    """Read ``000``, ``+07`` or ``-30`` as an integer."""
    if re.fullmatch(_SIGNED, text) is None:
        msg = f"not a signed value: {text!r}"
        raise CodecError(msg)
    return int(text)


def format_number(value: int) -> str:
    """Format a number as three digits (``080``)."""
    if not 0 <= value <= 999:  # noqa: PLR2004
        msg = f"number {value} out of range"
        raise CodecError(msg)
    return f"{value:03d}"


# ----- messages ------------------------------------------------------------------------------


def _spec(code: str) -> FamilySpec | None:
    return FAMILIES.get(code)


def _key_text(spec: FamilySpec | None, key: Mapping[str, str] | None) -> str:
    given = dict(key or {})
    if spec is None:
        if given:
            msg = "unknown CI family: no key fields known"
            raise CodecError(msg)
        return ""
    text = ""
    for item in spec.key:
        if item.name not in given:
            msg = f"CI {spec.code} needs the key field {item.name}"
            raise CodecError(msg)
        value = given.pop(item.name).ljust(DEFAULT_WIDTH)
        if re.fullmatch(r"[A-Za-z0-9 ]{3}", value) is None:
            msg = f"CI {spec.code}: bad {item.name} key {value!r}"
            raise CodecError(msg)
        text += item.name + value
    if given:
        msg = f"CI {spec.code}: unknown key fields {sorted(given)}"
        raise CodecError(msg)
    return text


def reply_code(code: str) -> str:
    """Return the code a reply carries on the wire (``sLCC``)."""
    return PREFIX + code


def query_message(code: str, key: Mapping[str, str] | None = None) -> str:
    """Build the read message, for example ``sLCCQSTNMMMM1``; ``key`` names the record.

    A family with a key does not answer without it, so the key is required.
    """
    spec = _spec(code)
    asked = spec.query if spec is not None and spec.query else code
    return f"{PREFIX}{asked}{QUERY}{_key_text(spec, key)}"


def encode_set(code: str, changes: Mapping[str, str], key: Mapping[str, str] | None = None) -> str:
    """Build the partial set message: key fields plus only the changed fields.

    Raises ``CiRefusedError`` for a read-only or unknown family or field and ``CodecError``
    for a value that does not fit. The receiver sends no reply: read the record back.
    """
    spec = _spec(code)
    if spec is None:
        raise CiRefusedError(code, "unknown family")
    if not spec.writable:
        raise CiRefusedError(code, spec.reason or "read-only")
    if not changes:
        msg = f"CI {code}: nothing to change"
        raise CodecError(msg)
    text = _key_text(spec, key)
    for name, value in changes.items():
        field_spec = spec.fields.get(name)
        if field_spec is None:
            msg = f"CI {code} has no settable field {name!r}"
            raise CodecError(msg)
        if not field_spec.writable:
            raise CiRefusedError(code, f"field {name} is read-only")
        text += name + field_spec.normalise(value)
    return PREFIX + code + text


@dataclass(frozen=True, slots=True)
class CiChange:
    """One planned set: what to send, what it replaces and how to undo it."""

    code: str
    key: Mapping[str, str]
    changes: Mapping[str, str]
    """The new values as sent (padded)."""
    before: CiRecord
    set_message: str
    restore_message: str
    """Puts the old values of exactly the changed fields back."""
    calibration: bool
    after: CiRecord | None = field(default=None, compare=False)
    """The record read back after the set (filled in by ``Receiver.ci_set``)."""

    @property
    def old(self) -> dict[str, str]:
        """The old values of the changed fields."""
        return {name: self.before.get(name) or "" for name in self.changes}


def plan_set(
    before: CiRecord, changes: Mapping[str, str], key: Mapping[str, str] | None = None
) -> CiChange:
    """Plan a set against the record read just before it, and build the restore command.

    ``before`` must be the record the set will change (read with the same key). Every changed
    field must be in it, so the old value is known and the set can be undone.
    """
    spec = _spec(before.code)
    key = dict(before.key if key is None else key)
    set_message = encode_set(before.code, changes, key)
    old: dict[str, str] = {}
    for name in changes:
        value = before.get(name)
        if value is None:
            msg = f"CI {before.code}: field {name} is not in the record, cannot restore it"
            raise CodecError(msg)
        old[name] = value
    new = {name: _normalised(before.code, name, value) for name, value in changes.items()}
    return CiChange(
        code=before.code,
        key=key,
        changes=new,
        before=before,
        set_message=set_message,
        restore_message=encode_set(before.code, old, key),
        calibration=spec.calibration if spec is not None else False,
    )


def _normalised(code: str, name: str, value: str) -> str:
    spec = FAMILIES[code]
    return spec.fields[name].normalise(value)


def applied(record: CiRecord, values: Mapping[str, str]) -> bool:
    """Return True when ``record`` holds every value of ``values``."""
    return all(record.get(name) == value for name, value in values.items())


def key_combinations(codes: Iterable[str]) -> Iterator[tuple[str, dict[str, str]]]:
    """Every (code, key) a complete read of the families ``codes`` needs."""
    for code in codes:
        spec = FAMILIES[code]
        for key in spec.all_keys():
            yield code, key
