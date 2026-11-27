"""Parse and format parameter values (no Home Assistant, no network).

``decode(command, param)`` turns the parameter the receiver sent into a Python value and
``encode(command, value)`` turns a value into the parameter to send, for each ``Value`` kind of
``commands.py``:

| Kind | Python value | Example |
|---|---|---|
| ENUM | option key (``str``; the raw parameter without options) | ``"01"`` -> ``"on"`` |
| HEX | raw ``int`` | ``"7C"`` -> 124 |
| SIGNED_HEX | ``float`` in the command's unit (steps times ``command.step``) | ``"-0A"`` -> -5.0 |
| SIGNED_DEC | ``int`` | ``"+005"`` -> 5, ``"0000"`` -> 0 |
| TONE | ``Tone`` (decode), ``TonePart`` (encode: one side) | ``"B-2T00"`` |
| SLOTS | ``DiracState`` (decode), option key (encode) | ``"112"`` -> slot 3 active |
| SLEEP | minutes as ``int`` (0 is ``OFF``) | ``"1E"`` -> 30 |
| TEXT | ``AudioInfo`` (``IFA``), ``VideoInfo`` (``IFV``), Celsius (``TPD``), else ``str`` | |
| HEX_TEXT | the front display text | |
| XML | ``DeviceInfo`` (``NRI``) | |
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal
from xml.etree import ElementTree as ET

from .commands import DIRAC_SLOTS, Command, Value
from .exceptions import CodecError

if TYPE_CHECKING:
    from collections.abc import Mapping

NOT_AVAILABLE = "N/A"
SLEEP_OFF = "OFF"
_HEX_BASE = 16
_DEC_ZERO = "0000"
_SIGNED_HEX_ZERO = "000"
_SLOT_ACTIVE = "2"
_SLOT_FILLED = "1"
_FLD_GLYPHS: Mapping[int, str] = {0x95: ".5", 0x90: ".0"}
_FLD_DROPPED = frozenset({0x12, 0x13})
_TEMPERATURE = re.compile(r"C\s*(-?\d+)")
_ZONE_IDS = {"1": "main", "2": "zone2", "3": "zone3", "4": "zone4"}
_ZONE_BITS = (("main", 1), ("zone2", 2), ("zone3", 4), ("zone4", 8))

type Decoded = (
    str | int | float | Tone | DiracState | AudioInfo | VideoInfo | DeviceInfo | None
)  # what ``decode`` returns


@dataclass(frozen=True, slots=True)
class Tone:
    """Bass and treble in dB."""

    bass: int
    treble: int


@dataclass(frozen=True, slots=True)
class TonePart:
    """One side of the tone pair, the form a set takes (``B+1``)."""

    side: Literal["bass", "treble"]
    level: int


@dataclass(frozen=True, slots=True)
class DiracState:
    """What ``DSS`` says: the active option and the filled slots, as option keys."""

    active: str
    """``off`` or ``slot_1`` to ``slot_3``."""
    filled: tuple[str, ...]
    """Slots that hold a measurement (active or not)."""


@dataclass(frozen=True, slots=True)
class AudioInfo:
    """``IFA`` fields; a missing field is an empty string."""

    input_port: str = ""
    input_format: str = ""
    sample_rate: str = ""
    input_channels: str = ""
    listening_mode: str = ""
    """The receiver's name for the current mode (several codes can show one name)."""
    output_channels: str = ""

    @property
    def summary(self) -> str:
        """Short text for a sensor: ``Dolby Atmos/TrueHD 48 kHz``."""
        return " ".join(part for part in (self.input_format, self.sample_rate) if part)


@dataclass(frozen=True, slots=True)
class VideoInfo:
    """``IFV`` fields; a missing field is an empty string."""

    input_port: str = ""
    input_resolution: str = ""
    input_color_format: str = ""
    input_depth: str = ""
    output: str = ""
    output_resolution: str = ""
    output_color_format: str = ""
    output_depth: str = ""
    hdr: str = ""

    @property
    def summary(self) -> str:
        """Short text for a sensor: input resolution plus HDR."""
        return " ".join(part for part in (self.input_resolution, self.hdr) if part)


@dataclass(frozen=True, slots=True)
class NetZone:
    """One zone of the ``NRI`` zone list."""

    id: str
    name: str
    enabled: bool
    volume_max: int
    volume_step: int


@dataclass(frozen=True, slots=True)
class NetInput:
    """One input of the ``NRI`` selector list."""

    code: str
    """The ``SLI`` parameter, upper case."""
    name: str
    enabled: bool
    zones: frozenset[str]


@dataclass(frozen=True, slots=True)
class DeviceInfo:
    """What ``NRI`` says about the receiver."""

    brand: str
    model: str
    year: str
    mac: str
    firmware: str
    friendly_name: str
    zones: tuple[NetZone, ...]
    inputs: tuple[NetInput, ...]


# ----- public entry points -----------------------------------------------------------------


def decode(command: Command, param: str) -> Decoded:  # noqa: C901, PLR0911
    """Turn the parameter of a message into a Python value (see the module docstring)."""
    if param == NOT_AVAILABLE:
        msg = f"{command.code} is not available (N/A)"
        raise CodecError(msg)
    try:
        match command.value:
            case Value.ENUM:
                return command.options.get(param, param)
            case Value.HEX:
                return int(param, _HEX_BASE)
            case Value.SIGNED_HEX:
                return decode_signed_hex(param) * (command.step or 1)
            case Value.SIGNED_DEC:
                return int(param)
            case Value.TONE:
                return decode_tone(param)
            case Value.SLOTS:
                return decode_slots(param)
            case Value.SLEEP:
                return decode_sleep(param)
            case Value.HEX_TEXT:
                return decode_display(param)
            case Value.XML:
                return parse_device_info(param)
            case Value.TEXT:
                return _decode_text(command.code, param)
    except ValueError as err:
        msg = f"cannot decode {command.code}{param}: {err}"
        raise CodecError(msg) from err
    msg = f"no codec for {command.value}"  # pragma: no cover
    raise CodecError(msg)  # pragma: no cover


def encode(command: Command, value: object) -> str:  # noqa: PLR0911
    """Turn a Python value into the parameter to send (see the module docstring)."""
    try:
        match command.value:
            case Value.ENUM:
                return _encode_enum(command, str(value))
            case Value.HEX:
                return f"{_number(value):02X}"
            case Value.SIGNED_HEX:
                return encode_signed_hex(round(_number(value) / (command.step or 1)))
            case Value.SIGNED_DEC:
                return encode_signed_dec(round(_number(value)))
            case Value.TONE:
                return _encode_tone(value)
            case Value.SLOTS:
                return _encode_slot(str(value))
            case Value.SLEEP:
                return encode_sleep(round(_number(value)))
            case _:
                msg = f"{command.code} has no encoder ({command.value})"
                raise CodecError(msg)
    except (TypeError, ValueError) as err:
        if isinstance(err, CodecError):
            raise
        msg = f"cannot encode {value!r} for {command.code}: {err}"
        raise CodecError(msg) from err


# ----- numbers -----------------------------------------------------------------------------


def _number(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        msg = f"{value!r} is not a number"
        raise CodecError(msg)
    return value


def decode_signed_hex(param: str) -> int:
    """``-0A`` is -10 steps, ``000`` is zero, ``+18`` is 24 steps."""
    if param == _SIGNED_HEX_ZERO or param.strip("0") == "":
        return 0
    if param[:1] not in {"+", "-"}:
        msg = f"no sign in {param!r}"
        raise CodecError(msg)
    steps = int(param[1:], _HEX_BASE)
    return steps if param[0] == "+" else -steps


def encode_signed_hex(steps: int) -> str:
    """Write steps the way the receiver does (zero is ``000``, two hex digits otherwise)."""
    if steps == 0:
        return _SIGNED_HEX_ZERO
    return f"{'+' if steps > 0 else '-'}{abs(steps):02X}"


def encode_signed_dec(value: int) -> str:
    """``+005``, ``-100``; zero is ``0000`` (the form the receiver reads and accepts)."""
    if value == 0:
        return _DEC_ZERO
    return f"{'+' if value > 0 else '-'}{abs(value):03d}"


def volume_fraction(raw: int, volume_max: int) -> float:
    """Volume as 0.0 to 1.0 of the receiver's maximum (``volume_max`` from the capabilities)."""
    return 0.0 if volume_max <= 0 else min(max(raw / volume_max, 0.0), 1.0)


def volume_raw(fraction: float, volume_max: int) -> int:
    """Return the raw volume for a 0.0 to 1.0 fraction."""
    return round(min(max(fraction, 0.0), 1.0) * volume_max)


def volume_db(raw: int, *, half_db: bool) -> float | None:
    """Volume in dB on 0.5 dB models (raw 0x7C is -20.0 dB); ``None`` on other models."""
    return raw / 2 - 82 if half_db else None


# ----- tone, Dirac, sleep -------------------------------------------------------------------


def _tone_side(text: str) -> int:
    if text == "00":
        return 0
    if len(text) != 2 or text[0] not in {"+", "-"}:  # noqa: PLR2004
        msg = f"bad tone value {text!r}"
        raise CodecError(msg)
    level = int(text[1], _HEX_BASE)
    return level if text[0] == "+" else -level


def decode_tone(param: str) -> Tone:
    """``B-2T00`` is bass -2 dB, treble 0 dB."""
    match = re.fullmatch(r"B(.{2})T(.{2})", param)
    if match is None:
        msg = f"bad tone pair {param!r}"
        raise CodecError(msg)
    return Tone(_tone_side(match[1]), _tone_side(match[2]))


def _tone_text(level: int) -> str:
    return "00" if level == 0 else f"{'+' if level > 0 else '-'}{abs(level):X}"


def _encode_tone(value: object) -> str:
    if not isinstance(value, TonePart):
        msg = "a tone is set one side at a time: pass a TonePart"
        raise CodecError(msg)
    return f"{'B' if value.side == 'bass' else 'T'}{_tone_text(value.level)}"


def decode_slots(param: str) -> DiracState:
    """``DSS112``: one digit per slot, 2 active, 1 filled, 0 empty; all 1 or 0 means off."""
    if len(param) < 1 or any(char not in "012" for char in param):
        msg = f"bad Dirac slots {param!r}"
        raise CodecError(msg)
    active = "off"
    filled: list[str] = []
    for index, char in enumerate(param, start=1):
        if char == _SLOT_ACTIVE:
            active = f"slot_{index}"
        if char != "0":
            filled.append(f"slot_{index}")
    return DiracState(active, tuple(filled))


def _encode_slot(option: str) -> str:
    for param, key in DIRAC_SLOTS.items():
        if key == option:
            return param
    msg = f"unknown Dirac option {option!r}"
    raise CodecError(msg)


def decode_sleep(param: str) -> int:
    """Minutes; ``OFF`` is 0."""
    return 0 if param == SLEEP_OFF else int(param, _HEX_BASE)


def encode_sleep(minutes: int) -> str:
    """``OFF`` for 0, else hex minutes."""
    return SLEEP_OFF if minutes <= 0 else f"{minutes:02X}"


def _encode_enum(command: Command, key: str) -> str:
    for param, option in command.options.items():
        if option == key:
            return param
    if not command.options or key in command.options:
        return key  # a raw parameter is accepted as it is
    msg = f"{key!r} is not an option of {command.code}"
    raise CodecError(msg)


# ----- text fields -------------------------------------------------------------------------


def _fields(param: str, count: int) -> list[str]:
    parts = param.split(",")
    parts += [""] * (count - len(parts))
    return [part.strip() for part in parts]


def parse_audio_info(param: str) -> AudioInfo:
    """``IFA``: port, format, sample rate, input channels, mode name, output channels."""
    fields = _fields(param, 6)
    return AudioInfo(
        input_port=fields[0],
        input_format=fields[1],
        sample_rate=fields[2],
        input_channels=fields[3],
        listening_mode=fields[4],
        output_channels=fields[5],
    )


def parse_video_info(param: str) -> VideoInfo:
    """``IFV``: input (port, resolution, colour, depth), output (same four), HDR at field 10."""
    fields = _fields(param, 10)
    return VideoInfo(
        input_port=fields[0],
        input_resolution=fields[1],
        input_color_format=fields[2],
        input_depth=fields[3],
        output=fields[4],
        output_resolution=fields[5],
        output_color_format=fields[6],
        output_depth=fields[7],
        hdr=fields[9],
    )


def parse_temperature(param: str) -> float | None:
    """``TPD`` reads ``F 86C 30``: Fahrenheit then Celsius; returns Celsius."""
    match = _TEMPERATURE.search(param)
    return None if match is None else float(match[1])


def _decode_text(code: str, param: str) -> Decoded:
    if code == "IFA":
        return parse_audio_info(param)
    if code == "IFV":
        return parse_video_info(param)
    if code == "TPD":
        return parse_temperature(param)
    return param


def decode_display(param: str) -> str:
    r"""Read the front display (hex ASCII); ``\x95`` is ".5", ``\x90`` is ".0", logos dropped."""
    try:
        raw = bytes.fromhex(param)
    except ValueError as err:
        msg = f"bad display text {param!r}"
        raise CodecError(msg) from err
    text = "".join(_FLD_GLYPHS.get(byte, "" if byte in _FLD_DROPPED else chr(byte)) for byte in raw)
    return text.strip()


# ----- NRI ---------------------------------------------------------------------------------


def _zones_from_mask(mask: str) -> frozenset[str]:
    try:
        bits = int(mask, _HEX_BASE)
    except ValueError:
        return frozenset()
    return frozenset(zone for zone, bit in _ZONE_BITS if bits & bit)


def _int(text: str | None, default: int = 0) -> int:
    try:
        return int(text or default)
    except ValueError:
        return default


def parse_device_info(xml: str) -> DeviceInfo:
    """Read the ``NRI`` document."""
    try:
        root = ET.fromstring(xml)  # noqa: S314  (a local receiver, not the internet)
    except ET.ParseError as err:
        msg = f"bad NRI document: {err}"
        raise CodecError(msg) from err
    device = root.find("device")
    if device is None:
        msg = "NRI has no device element"
        raise CodecError(msg)

    def text(tag: str) -> str:
        return (device.findtext(tag) or "").strip()

    zones = tuple(
        NetZone(
            id=_ZONE_IDS.get(zone.get("id", ""), f"zone{zone.get('id', '')}"),
            name=zone.get("name", ""),
            enabled=_int(zone.get("value")) > 0,
            volume_max=_int(zone.get("volmax")),
            volume_step=_int(zone.get("volstep")),
        )
        for zone in device.findall("zonelist/zone")
    )
    inputs = tuple(
        NetInput(
            code=selector.get("id", "").upper(),
            name=selector.get("name", ""),
            enabled=_int(selector.get("value")) > 0,
            zones=_zones_from_mask(selector.get("zone", "0")),
        )
        for selector in device.findall("selectorlist/selector")
    )
    return DeviceInfo(
        brand=text("brand"),
        model=text("model"),
        year=text("year"),
        mac=text("macaddress").replace(":", "").upper(),
        firmware=text("firmwareversion"),
        friendly_name=text("friendlyname"),
        zones=zones,
        inputs=inputs,
    )
