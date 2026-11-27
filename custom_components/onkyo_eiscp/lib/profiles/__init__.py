"""Model profiles: what probing cannot see (listening modes per signal, refused option values)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from .base import Profile
from .tx_rz50 import TX_RZ50

if TYPE_CHECKING:
    from collections.abc import Mapping

PROFILES: Final[Mapping[str, Profile]] = {TX_RZ50.model: TX_RZ50}


def find_profile(model: str) -> Profile | None:
    """Return the profile of ``model`` (case does not matter), or ``None``."""
    wanted = model.strip().upper()
    for name, profile in PROFILES.items():
        if name.upper() == wanted:
            return profile
    return None


__all__ = ["PROFILES", "Profile", "find_profile"]
