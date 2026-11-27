"""Clean names for inputs and listening modes (ARCHITECTURE.md C5 "Clean names", RULES.md 14).

Pure functions over the capabilities, the entry options and the current values, so the media
player, the options flow and the card agree on one list.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Final

from .const import (
    CONF_HIDDEN,
    CONF_INPUT_ORDER,
    CONF_INPUTS,
    CONF_LISTENING_MODES,
    CONF_NAME,
    ZONE_MAIN,
)
from .lib.codecs import AudioInfo, parse_audio_info
from .lib.commands import LISTENING_MODES

if TYPE_CHECKING:
    from collections.abc import Mapping

    from .lib import Capabilities

MODE: Final = "LMD"
AUDIO_INFO: Final = "IFA"
INPUT: Final = "SLI"
PCM: Final = "pcm"
ATMOS: Final = "atmos"


def _entry(options: Mapping[str, Any], section: str, code: str) -> Mapping[str, Any]:
    """Return the stored options of one input or mode (empty when unchanged)."""
    entries = options.get(section) or {}
    return entries.get(code) or {}


def is_hidden(options: Mapping[str, Any], section: str, code: str) -> bool:
    """Return True when the user hid this input or mode."""
    return bool(_entry(options, section, code).get(CONF_HIDDEN, False))


def input_name(caps: Capabilities, options: Mapping[str, Any], code: str) -> str:
    """Return the user's name for an input, else the receiver's own, else the code."""
    custom = _entry(options, CONF_INPUTS, code).get(CONF_NAME)
    if custom:
        return str(custom)
    return next((item.name for item in caps.inputs if item.code == code), code)


def ordered_input_codes(caps: Capabilities, options: Mapping[str, Any]) -> list[str]:
    """Return every input code: the user's order first, then the receiver's order."""
    receiver_order = [item.code for item in caps.inputs]
    wanted = [code for code in options.get(CONF_INPUT_ORDER, []) if code in receiver_order]
    wanted = list(dict.fromkeys(wanted))
    return wanted + [code for code in receiver_order if code not in wanted]


def source_codes(
    caps: Capabilities, options: Mapping[str, Any], zone: str = ZONE_MAIN
) -> list[str]:
    """Return the input codes the source list offers: this zone's, in order, minus hidden."""
    in_zone = {item.code for item in caps.inputs if zone in item.zones}
    return [
        code
        for code in ordered_input_codes(caps, options)
        if code in in_zone and not is_hidden(options, CONF_INPUTS, code)
    ]


def table_mode_name(code: str) -> str:
    """Return the listening mode's name from the table, else the bare code."""
    mode = LISTENING_MODES.get(code)
    return mode.name if mode else code


def _table_names() -> frozenset[str]:
    return frozenset(mode.name for mode in LISTENING_MODES.values())


def mode_name(
    options: Mapping[str, Any],
    values: Mapping[str, str],
    code: str,
) -> str:
    """Return the name of one listening mode code.

    In this order: the user's rename; the receiver's own name for the current mode when it is
    not another code's table name (``80`` shows "Dolby Atmos" with an Atmos source); the table
    name.
    """
    custom = _entry(options, CONF_LISTENING_MODES, code).get(CONF_NAME)
    if custom:
        return str(custom)
    table = table_mode_name(code)
    if code == values.get(MODE):
        shown = audio_info(values).listening_mode
        if shown and (shown == table or shown not in _table_names()):
            return shown
    return table


def audio_info(values: Mapping[str, str]) -> AudioInfo:
    """Return the parsed ``IFA`` value (all fields empty when unknown)."""
    param = values.get(AUDIO_INFO, "")
    return parse_audio_info("" if param == "N/A" else param)


def signal_group(values: Mapping[str, str]) -> str | None:
    """Return ``pcm`` or ``atmos`` for the current signal, ``None`` for other formats."""
    fmt = audio_info(values).input_format
    if fmt.upper() in {"", "PCM"}:
        return PCM
    if "atmos" in fmt.lower():
        return ATMOS
    return None


def mode_codes(
    caps: Capabilities,
    options: Mapping[str, Any],
    values: Mapping[str, str],
) -> list[str]:
    """Return the listening mode codes to offer now, minus hidden (the current one stays)."""
    group = signal_group(values)
    codes = caps.signal_modes.get(group, caps.listening_modes) if group else caps.listening_modes
    current = values.get(MODE)
    shown = [
        code
        for code in codes
        if not is_hidden(options, CONF_LISTENING_MODES, code) or code == current
    ]
    if current and current != "N/A" and current not in shown:
        shown.append(current)
    return shown
