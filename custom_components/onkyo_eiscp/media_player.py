"""The main zone media player: power, volume, mute, source and listening mode."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, ClassVar

from homeassistant.components.media_player import (
    MediaPlayerEntity,
    MediaPlayerEntityFeature,
    MediaPlayerState,
)
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError

from .const import (
    CONF_MAX_VOLUME,
    DOMAIN,
    ERROR_ZONE_POWER_REFUSED,
    ZONE_2,
    ZONE_3,
    ZONE_MAIN,
)
from .entity import OnkyoEntity, translated_errors
from .lib import COMMANDS, NotAvailableError
from .lib.codecs import encode, volume_db, volume_fraction, volume_raw
from .naming import (
    ZONE_FOLLOWS_MAIN,
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

#: Power, volume, mute and source code of each extra zone (ARCHITECTURE.md C5).
ZONE_CODES: dict[str, tuple[str, str, str, str]] = {
    ZONE_2: ("ZPW", "ZVL", "ZMT", "SLZ"),
    ZONE_3: ("PW3", "VL3", "MT3", "SL3"),
}

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
    """Add a player for the main zone and for each extra zone the receiver reports."""
    coordinator = entry.runtime_data
    caps = coordinator.data.capabilities
    players: list[MediaPlayerEntity] = []
    if caps.zone(ZONE_MAIN) is not None:
        players.append(OnkyoMainPlayer(coordinator))
    players.extend(
        OnkyoZonePlayer(coordinator, zone)
        for zone, codes in ZONE_CODES.items()
        if caps.zone(zone) is not None and codes[0] in caps.supported
    )
    async_add_entities(players)


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
        return min(int(chosen), top) if chosen is not None else top

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


class OnkyoZonePlayer(OnkyoEntity, MediaPlayerEntity):
    """Zone 2 or zone 3: power, source, mute and, while the receiver reports one, volume."""

    def __init__(self, coordinator: OnkyoCoordinator, zone: str) -> None:
        """Create the player of ``zone`` (``zone2`` or ``zone3``)."""
        super().__init__(coordinator, zone, zone)
        self._zone = zone
        self._power, self._volume, self._mute, self._source = ZONE_CODES[zone]
        self.watched = frozenset(ZONE_CODES[zone])

    @property
    def _options(self) -> dict[str, Any]:
        return dict(self.coordinator.config_entry.options)

    @property
    def _values(self) -> dict[str, str]:
        return dict(self.coordinator.data.values)

    @property
    def _has_volume(self) -> bool:
        """True while the volume code holds a number (it is N/A at a fixed output level)."""
        return self._raw_volume() is not None and self._volume not in (
            self.coordinator.data.unavailable
        )

    @property
    def _volume_max(self) -> int:
        zone = self.coordinator.data.capabilities.zone(self._zone)
        return zone.volume_max if zone else 100

    def _raw_volume(self) -> int | None:
        try:
            return int(self._values.get(self._volume, ""), 16)
        except ValueError:
            return None

    @property
    def supported_features(self) -> MediaPlayerEntityFeature:
        """Volume features only while the volume code holds a value (RULES.md 4)."""
        features = (
            MediaPlayerEntityFeature.TURN_ON
            | MediaPlayerEntityFeature.TURN_OFF
            | MediaPlayerEntityFeature.SELECT_SOURCE
        )
        if self._values.get(self._mute) in {"00", "01"}:
            features |= MediaPlayerEntityFeature.VOLUME_MUTE
        if self._has_volume:
            features |= MediaPlayerEntityFeature.VOLUME_SET | MediaPlayerEntityFeature.VOLUME_STEP
        return features

    @property
    def state(self) -> MediaPlayerState | None:
        """Return on, off, or unknown while the zone's power has not been read."""
        match self._values.get(self._power):
            case "01":
                return MediaPlayerState.ON
            case "00":
                return MediaPlayerState.OFF
            case _:
                return None

    @property
    def volume_level(self) -> float | None:
        """Return the volume as 0.0 to 1.0 of the zone's maximum (RULES.md 16)."""
        raw = self._raw_volume()
        if raw is None or not self._has_volume:
            return None
        return volume_fraction(raw, self._volume_max)

    @property
    def is_volume_muted(self) -> bool | None:
        """Return True while the zone is muted."""
        param = self._values.get(self._mute)
        return None if param not in {"00", "01"} else param == "01"

    def _source_codes(self) -> list[str]:
        caps = self.coordinator.data.capabilities
        codes = source_codes(caps, self._options, self._zone)
        # NRI lists "Source" (80) for the zones; add it when a model leaves it out.
        return codes if ZONE_FOLLOWS_MAIN in codes else [*codes, ZONE_FOLLOWS_MAIN]

    def _source_name(self, code: str) -> str:
        caps = self.coordinator.data.capabilities
        if code == ZONE_FOLLOWS_MAIN and all(item.code != code for item in caps.inputs):
            return "Source"
        return input_name(caps, self._options, code)

    @property
    def source(self) -> str | None:
        """Return the current input's name (``Source`` when the zone follows the main zone)."""
        code = self._values.get(self._source)
        if not code or code == "N/A":
            return None
        return self._source_name(code)

    @property
    def source_list(self) -> list[str]:
        """Return the zone's inputs by their clean names, then ``Source``."""
        names = [self._source_name(code) for code in self._source_codes()]
        if (current := self.source) and current not in names:
            names.append(current)
        return names

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the dB volume and the source code (for the card)."""
        attributes: dict[str, Any] = {"source_code": self._values.get(self._source)}
        raw = self._raw_volume()
        zone = self.coordinator.data.capabilities.zone(self._zone)
        if raw is not None and zone is not None and self._has_volume:
            attributes["volume_db"] = volume_db(raw, half_db=zone.half_db)
        return attributes

    async def async_turn_on(self) -> None:
        """Power the zone on; zone 3 on the TX-RZ50 is refused (``zone_power_refused``)."""
        try:
            with translated_errors():
                reply = await self.coordinator.receiver.set(self._power, "01")
        except HomeAssistantError as err:
            if isinstance(err.__cause__, NotAvailableError):
                raise _refused() from err
            raise
        if reply != "01":
            raise _refused()

    async def async_turn_off(self) -> None:
        """Put the zone in standby."""
        await self._set(self._power, "00")

    async def async_set_volume_level(self, volume: float) -> None:
        """Set the volume; 1.0 is the zone's maximum."""
        await self._set_raw_volume(volume_raw(volume, self._volume_max))

    async def async_volume_up(self) -> None:
        """Raise the volume by about 1 dB."""
        await self._step_volume(1)

    async def async_volume_down(self) -> None:
        """Lower the volume by about 1 dB."""
        await self._step_volume(-1)

    async def _step_volume(self, direction: int) -> None:
        zone = self.coordinator.data.capabilities.zone(self._zone)
        step = 2 if zone and zone.half_db else 1
        await self._set_raw_volume((self._raw_volume() or 0) + direction * step)

    async def _set_raw_volume(self, raw: int) -> None:
        raw = min(max(raw, 0), self._volume_max)
        await self._set(self._volume, encode(COMMANDS[self._volume], raw))

    async def async_mute_volume(self, mute: bool) -> None:  # noqa: FBT001
        """Mute or unmute the zone."""
        await self._set(self._mute, "01" if mute else "00")

    async def async_select_source(self, source: str) -> None:
        """Select an input by its clean name."""
        for code in self._source_codes():
            if self._source_name(code) == source:
                await self._set(self._source, code)
                return
        error = _unknown("unknown_source", source)
        raise error

    async def _set(self, code: str, param: str) -> None:
        with translated_errors():
            await self.coordinator.receiver.set(code, param)


def _refused() -> HomeAssistantError:
    return HomeAssistantError(translation_domain=DOMAIN, translation_key=ERROR_ZONE_POWER_REFUSED)
