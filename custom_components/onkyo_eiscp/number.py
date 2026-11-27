"""Number entities: tone, levels, vocal enhancer, dialog level, AV sync, sleep timer."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.const import EntityCategory, UnitOfTime

from .lib import COMMANDS
from .lib.codecs import Tone, TonePart, encode
from .lib.commands import Value
from .setting import OnkyoSetting

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

    from . import OnkyoConfigEntry
    from .coordinator import OnkyoCoordinator

PARALLEL_UPDATES = 1

TONE = "TFR"
DB = "dB"
_UNITS = {"ms": UnitOfTime.MILLISECONDS, "min": UnitOfTime.MINUTES, "dB": DB}


@dataclass(frozen=True, slots=True)
class NumberRow:
    """One number of C5; the range, step and unit come from the command table."""

    key: str
    code: str
    category: EntityCategory | None = None
    enabled_default: bool = True


ROWS = (
    NumberRow("subwoofer_level", "SWL"),
    NumberRow("subwoofer2_level", "SW2", enabled_default=False),
    NumberRow("center_level", "CTL"),
    NumberRow("vocal_enhancer", "VOC"),
    NumberRow("dialog_level", "DLC"),
    NumberRow("av_sync", "AVS", EntityCategory.CONFIG),
    NumberRow("sleep_timer", "SLP"),
)


async def async_setup_entry(
    hass: HomeAssistant,  # noqa: ARG001
    entry: OnkyoConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add the numbers whose code the receiver answered."""
    coordinator = entry.runtime_data
    supported = coordinator.data.capabilities.supported
    entities: list[OnkyoSetting] = [
        OnkyoNumber(coordinator, row) for row in ROWS if row.code in supported
    ]
    if TONE in supported:
        entities.extend(OnkyoToneNumber(coordinator, side) for side in ("bass", "treble"))
    async_add_entities(entities)


class _Range(OnkyoSetting, NumberEntity):
    """Range, step and unit from the command table."""

    _attr_mode = NumberMode.SLIDER

    def _describe(self) -> None:
        command = self._command
        self._attr_native_min_value = float(command.minimum or 0)
        self._attr_native_max_value = float(command.maximum or 0)
        self._attr_native_step = float(command.step or 1)
        self._attr_native_unit_of_measurement = _UNITS.get(command.unit)


class OnkyoNumber(_Range):
    """A number over one code (levels, enhancer, AV sync, sleep timer)."""

    def __init__(self, coordinator: OnkyoCoordinator, row: NumberRow) -> None:
        """Create the number for one row."""
        super().__init__(coordinator, row.key, row.code)
        self._describe()
        self._attr_entity_category = row.category
        self._attr_entity_registry_enabled_default = row.enabled_default

    @property
    def native_value(self) -> float | None:
        """Return the value in the unit of the command."""
        value = self._decoded()
        return float(value) if isinstance(value, int | float) else None

    async def async_set_native_value(self, value: float) -> None:
        """Send the value; only the dB levels take fractions."""
        number: float = value if self._command.value is Value.SIGNED_HEX else round(value)
        await self._send(encode(self._command, number))


class OnkyoToneNumber(_Range):
    """Bass or treble: one side of ``TFR`` (a set writes one side)."""

    def __init__(self, coordinator: OnkyoCoordinator, side: str) -> None:
        """Create the bass or treble number."""
        super().__init__(coordinator, side, TONE)
        self._side = side
        self._describe()

    @property
    def native_value(self) -> float | None:
        """Return the side's level in dB."""
        value = self._decoded()
        if not isinstance(value, Tone):
            return None
        return float(value.bass if self._side == "bass" else value.treble)

    async def async_set_native_value(self, value: float) -> None:
        """Set one side, leaving the other as it is."""
        side = "bass" if self._side == "bass" else "treble"
        await self._send(encode(COMMANDS[TONE], TonePart(side, round(value))))
