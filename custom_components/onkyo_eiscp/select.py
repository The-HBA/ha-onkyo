"""Select entities: Dirac Live slot, late night, dimmer, equalizer, digital filter, HDMI output."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from homeassistant.components.select import SelectEntity
from homeassistant.const import EntityCategory
from homeassistant.exceptions import ServiceValidationError

from .const import DOMAIN
from .lib import COMMANDS
from .lib.codecs import DiracState, encode
from .setting import OnkyoSetting

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

    from . import OnkyoConfigEntry
    from .coordinator import OnkyoCoordinator

PARALLEL_UPDATES = 1

DIRAC = "DSS"
DIRAC_OFF = "off"


@dataclass(frozen=True, slots=True)
class SelectRow:
    """One enum select of C5."""

    key: str
    code: str
    category: EntityCategory | None = None
    enabled_default: bool = True


ROWS = (
    SelectRow("late_night", "LTN"),
    SelectRow("dimmer", "DIM"),
    SelectRow("equalizer", "EQS"),
    SelectRow("digital_filter", "DGF", EntityCategory.CONFIG),
    SelectRow("hdmi_output", "HDO", EntityCategory.CONFIG, enabled_default=False),
)


async def async_setup_entry(
    hass: HomeAssistant,  # noqa: ARG001
    entry: OnkyoConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add the selects whose code the receiver answered."""
    coordinator = entry.runtime_data
    caps = coordinator.data.capabilities
    entities: list[OnkyoSetting] = [
        OnkyoEnumSelect(coordinator, row) for row in ROWS if row.code in caps.supported
    ]
    if DIRAC in caps.supported:
        entities.append(OnkyoDiracSelect(coordinator))
    async_add_entities(entities)


class OnkyoEnumSelect(OnkyoSetting, SelectEntity):
    """A select over an enum code; options come from the capabilities (model profile)."""

    def __init__(self, coordinator: OnkyoCoordinator, row: SelectRow) -> None:
        """Create the select for one row."""
        super().__init__(coordinator, row.key, row.code)
        self._attr_entity_category = row.category
        self._attr_entity_registry_enabled_default = row.enabled_default

    def _allowed(self) -> list[str]:
        """Return the option keys the model allows, in table order."""
        params = self.coordinator.data.capabilities.options.get(self._code, ())
        return [self._command.options.get(param, param) for param in params]

    @property
    def current_option(self) -> str | None:
        """Return the option key of the current value."""
        value = self._decoded()
        return value if isinstance(value, str) else None

    @property
    def options(self) -> list[str]:
        """Return the allowed options, minus those refused now; the current one always stays.

        A refused option (``LTN02`` with PCM) is left out only while the listening mode that
        refused it is active; it comes back with the mode (``Receiver.refused_options``).
        """
        refused = self.coordinator.receiver.refused_options.get(self._code, frozenset())
        refused_keys = {self._command.options.get(param, param) for param in refused}
        current = self.current_option
        return [
            option for option in self._allowed() if option not in refused_keys or option == current
        ]

    async def async_select_option(self, option: str) -> None:
        """Send the option to the receiver."""
        await self._send(encode(self._command, option))


class OnkyoDiracSelect(OnkyoSetting, SelectEntity):
    """Dirac Live: off or one of the filled slots (RULES.md 13: slot choice only)."""

    def __init__(self, coordinator: OnkyoCoordinator) -> None:
        """Create the Dirac slot select."""
        super().__init__(coordinator, "dirac_slot", DIRAC)

    def _state(self) -> DiracState | None:
        value = self._decoded()
        return value if isinstance(value, DiracState) else None

    @property
    def current_option(self) -> str | None:
        """Return ``off`` or the active slot."""
        state = self._state()
        return None if state is None else state.active

    @property
    def options(self) -> list[str]:
        """Return ``off`` and the filled slots; the active one always stays."""
        state = self._state()
        if state is None:
            return [DIRAC_OFF]
        slots = {*state.filled, state.active} - {DIRAC_OFF}
        return [DIRAC_OFF, *sorted(slots)]

    async def async_select_option(self, option: str) -> None:
        """Choose a slot or turn Dirac off."""
        if option not in self.options:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="unknown_option",
                translation_placeholders={"name": option},
            )
        await self._send(encode(COMMANDS[DIRAC], option))
