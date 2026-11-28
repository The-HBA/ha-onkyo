"""TX-RZ50 (firmware R145-1119-1284-0034), from the survey of 2026-11-26 and 2026-11-27.

The listening mode lists are the ones the receiver offered with a PCM stereo and a TrueHD Atmos
signal; the option limits are the parameters it accepted (the others answered ``N/A`` or were
ignored). Lists follow the order of ``commands.LISTENING_MODES``.
"""

from __future__ import annotations

from typing import Final

from custom_components.onkyo_eiscp.lib.commands import LISTENING_MODES

from .base import Profile

# The 23 modes the receiver offers with PCM stereo (survey session 33) and 15 with TrueHD Atmos.
_PCM: Final = frozenset(
    {
        *("82", "84", "85", "8B", "8C", "89", "8A", "08", "09", "0A", "0B", "03"),
        *("05", "06", "0E", "0C", "13", "0D", "11", "01", "00", "0F", "80"),
    }
)
_ATMOS: Final = frozenset(
    {"80", "08", "09", "0A", "0B", "03", "05", "06", "0E", "0C", "13", "0D", "11", "01", "00"}
)
_DTS_HD_96K: Final = "40"  # shown for DTS-HD 96 kHz 7.1 ("DTS-HD" in IFA)


def _ordered(codes: frozenset[str]) -> tuple[str, ...]:
    return tuple(code for code in LISTENING_MODES if code in codes)


TX_RZ50: Final = Profile(
    model="TX-RZ50",
    listening_modes=_ordered(_PCM | {_DTS_HD_96K}),
    signal_modes={"pcm": _ordered(_PCM), "atmos": _ordered(_ATMOS)},
    options={
        "DIM": ("00", "01", "02"),
        "DGF": ("00", "01", "03"),
        # OSD AUDIO and VIDEO do nothing on this model (checked by its owner, 2026-11-28); NRI
        # has no control for them. HOME goes through NRI (Home is 0).
        "OSD": ("UP", "DOWN", "LEFT", "RIGHT", "ENTER", "EXIT", "MENU", "HOME", "QUICK"),
    },
    notes="No centre speaker, one subwoofer; DGF02 is ignored, DIM03 and DIM08 answer N/A.",
)
