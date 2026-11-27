"""The profile record."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping


@dataclass(frozen=True, slots=True)
class Profile:
    """What is known about one model beyond what its answers show."""

    model: str
    listening_modes: tuple[str, ...]
    """Listening mode codes the model offers, in display order."""
    signal_modes: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    """Mode codes per signal group (``pcm``, ``atmos``); other groups use ``listening_modes``."""
    options: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    """Allowed set parameters per enum code, where fewer than the table lists."""
    notes: str = ""
