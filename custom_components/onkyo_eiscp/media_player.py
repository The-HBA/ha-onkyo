"""The main zone media player: power, volume, mute, source and listening mode."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, ClassVar

from homeassistant.components.media_player import (
    MediaPlayerEntity,
    MediaPlayerEntityFeature,
    MediaPlayerState,
)
from homeassistant.exceptions import ServiceValidationError

from .const import CONF_MAX_VOLUME, DOMAIN, ZONE_MAIN
from .entity import OnkyoEntity, translated_errors
from .lib import COMMANDS
from .lib.codecs import encode, volume_db, volume_fraction, volume_raw
from .naming import (
    input_name,
    mode_codes,
    mode_name,
    source_codes,
)

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

    from . import OnkyoConfigEntry
    from .coordinator import OnkyoCoordinator

PARALLEL_UPDATES = 1

_FEATURES = (
    MediaPlayerEntityFeature.TURN_ON
    | MediaPlayerEntityFeature.TURN_OFF
    | MediaPlayerEntityFeature.VOLUME_SET
    | MediaPlayerEntityFeature.VOLUME_STEP
    | MediaPlayerEntityFeature.VOLUME_MUTE
    | MediaPlayerEntityFeature.SELECT_SOURCE
    | MediaPlayerEntityFeature.SELECT_SOUND_MODE
)


async def async_setup_entry(
    hass: HomeAssistant,  # noqa: ARG001
    entry: OnkyoConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add the main zone player (zones 2 and 3 come with P3.S2)."""
    coordinator = entry.runtime_data
    if coordinator.data.capabilities.zone(ZONE_MAIN) is not None:
        async_add_entities([OnkyoMainPlayer(coordinator)])


class OnkyoMainPlayer(OnkyoEntity, MediaPlayerEntity):
    """The main zone."""

    _attr_name = None
    _attr_supported_features = _FEATURES
    watched: ClassVar[frozenset[str]] = frozenset({"PWR", "MVL", "AMT", "SLI", "LMD", "IFA"})

    def __init__(self, coordinator: OnkyoCoordinator) -> None:
        """Create the main zone player."""
        super().__init__(coordinator, ZONE_MAIN, "main")

    # ----- helpers --------------------------------------------------------------------------

    @property
    def _options(self) -> dict[str, Any]:
        return dict(self.coordinator.config_entry.options)

    @property
    def _values(self) -> dict[str, str]:
        return dict(self.coordinator.data.values)

    @property
    def _volume_max(self) -> int:
        """Raw volume that counts as 100 % (the user's maximum, else the receiver's)."""
        zone = self.coordinator.data.capabilities.zone(ZONE_MAIN)
        top = zone.volume_max if zone else 100
        chosen = self._options.get(CONF_MAX_VOLUME)
        return min(int(chosen), top) if chosen else top

    def _raw_volume(self) -> int | None:
        param = self._values.get("MVL", "")
        try:
            return int(param, 16)
        except ValueError:
            return None

    # ----- state ----------------------------------------------------------------------------

    @property
    def state(self) -> MediaPlayerState | None:
        """Return on, off, or unknown while the power state has not been read."""
        match self._values.get("PWR"):
            case "01":
                return MediaPlayerState.ON
            case "00":
                return MediaPlayerState.OFF
            case _:
                return None

    @property
    def volume_level(self) -> float | None:
        """Return the volume, 1.0 at the maximum volume option (RULES.md 16)."""
        raw = self._raw_volume()
        return None if raw is None else volume_fraction(raw, self._volume_max)

    @property
    def is_volume_muted(self) -> bool | None:
        """Return True while muted."""
        param = self._values.get("AMT")
        return None if param in {None, "N/A"} else param == "01"

    @property
    def source(self) -> str | None:
        """Return the current input's name (a hidden current input still shows)."""
        code = self._values.get("SLI")
        if not code or code == "N/A":
            return None
        return input_name(self.coordinator.data.capabilities, self._options, code)

    @property
    def source_list(self) -> list[str]:
        """Return the visible inputs by their clean names, in the user's order."""
        caps = self.coordinator.data.capabilities
        options = self._options
        names = [input_name(caps, options, code) for code in source_codes(caps, options)]
        if (current := self.source) and current not in names:
            names.append(current)
        return names

    @property
    def sound_mode(self) -> str | None:
        """Return the current listening mode's clean name."""
        code = self._values.get("LMD")
        if not code or code == "N/A":
            return None
        return mode_name(self._options, self._values, code)

    @property
    def sound_mode_list(self) -> list[str]:
        """Return the listening modes for the current signal, by clean names."""
        return [mode_name(self._options, self._values, code) for code in self._mode_codes()]

    def _mode_codes(self) -> list[str]:
        return mode_codes(self.coordinator.data.capabilities, self._options, self._values)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the dB volume and the codes behind the names (for the card)."""
        raw = self._raw_volume()
        zone = self.coordinator.data.capabilities.zone(ZONE_MAIN)
        attributes: dict[str, Any] = {
            "source_code": self._values.get("SLI"),
            "sound_mode_code": self._values.get("LMD"),
            "sound_mode_codes": self._mode_codes(),
        }
        if raw is not None and zone is not None:
            attributes["volume_db"] = volume_db(raw, half_db=zone.half_db)
        return attributes

    # ----- actions --------------------------------------------------------------------------

    async def async_turn_on(self) -> None:
        """Power the receiver on."""
        await self._set("PWR", "01")

    async def async_turn_off(self) -> None:
        """Put the receiver in standby."""
        await self._set("PWR", "00")

    async def async_set_volume_level(self, volume: float) -> None:
        """Set the volume; 1.0 is the maximum volume option."""
        await self._set_raw_volume(volume_raw(volume, self._volume_max))

    async def async_volume_up(self) -> None:
        """Raise the volume by about 1 dB (one raw step on models without dB)."""
        await self._step_volume(1)

    async def async_volume_down(self) -> None:
        """Lower the volume by about 1 dB."""
        await self._step_volume(-1)

    async def _step_volume(self, direction: int) -> None:
        raw = self._raw_volume() or 0
        zone = self.coordinator.data.capabilities.zone(ZONE_MAIN)
        step = 2 if zone and zone.half_db else 1
        await self._set_raw_volume(raw + direction * step)

    async def _set_raw_volume(self, raw: int) -> None:
        raw = min(max(raw, 0), self._volume_max)
        await self._set("MVL", encode(COMMANDS["MVL"], raw))

    async def async_mute_volume(self, mute: bool) -> None:  # noqa: FBT001
        """Mute or unmute."""
        await self._set("AMT", "01" if mute else "00")

    async def async_select_source(self, source: str) -> None:
        """Select an input by its clean name."""
        caps = self.coordinator.data.capabilities
        options = self._options
        for code in source_codes(caps, options):
            if input_name(caps, options, code) == source:
                await self._set("SLI", code)
                return
        if (current := self._values.get("SLI")) and self.source == source:
            await self._set("SLI", current)
            return
        error = _unknown("unknown_source", source)
        raise error

    async def async_select_sound_mode(self, sound_mode: str) -> None:
        """Select a listening mode by its clean name."""
        for code in self._mode_codes():
            if mode_name(self._options, self._values, code) == sound_mode:
                await self._set("LMD", code)
                return
        error = _unknown("unknown_sound_mode", sound_mode)
        raise error

    async def _set(self, code: str, param: str) -> None:
        with translated_errors():
            await self.coordinator.receiver.set(code, param)


def _unknown(key: str, name: str) -> ServiceValidationError:
    return ServiceValidationError(
        translation_domain=DOMAIN, translation_key=key, translation_placeholders={"name": name}
    )
