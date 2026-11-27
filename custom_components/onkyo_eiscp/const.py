"""Constants for the Onkyo eISCP integration (shared file: changes go through Lead)."""

from __future__ import annotations

from datetime import timedelta
from typing import Final

from homeassistant.const import Platform

DOMAIN: Final = "onkyo_eiscp"
#: The core integration for the same receivers; one connection per host means only one may run.
CORE_DOMAIN: Final = "onkyo"
DEFAULT_PORT: Final = 60128

PLATFORMS: Final = (
    Platform.MEDIA_PLAYER,
    Platform.NUMBER,
    Platform.REMOTE,
    Platform.SELECT,
    Platform.SENSOR,
    Platform.SWITCH,
)

#: Zone keys, as in ``lib.capabilities.ZoneInfo.id`` and the entity unique IDs.
ZONE_MAIN: Final = "main"
ZONE_2: Final = "zone2"
ZONE_3: Final = "zone3"

# Options (ARCHITECTURE.md C5 "Options").
CONF_INPUTS: Final = "inputs"
CONF_LISTENING_MODES: Final = "listening_modes"
CONF_NAME: Final = "name"
CONF_HIDDEN: Final = "hidden"
#: Raw volume units (MVL); the form shows dB on 0.5 dB models.
CONF_MAX_VOLUME: Final = "max_volume"
#: Put the volume back after power-on (the TX-RZ50 jumps to -20 dB).
CONF_RESTORE_VOLUME: Final = "restore_volume"
#: Input codes in the order the source list shows them (drag to reorder).
CONF_INPUT_ORDER: Final = "input_order"
DEFAULT_RESTORE_VOLUME: Final = True

#: The temperature is not pushed; poll it while its sensor is enabled and the receiver is on.
TEMPERATURE_INTERVAL: Final = timedelta(minutes=5)

# Actions and websocket.
SERVICE_SEND_RAW: Final = "send_raw"
SERVICE_SURVEY: Final = "survey"
ATTR_CONFIG_ENTRY_ID: Final = "config_entry_id"
ATTR_MESSAGE: Final = "message"
WS_CARD_INFO: Final = "onkyo_eiscp/card_info"

# Translation keys for errors and repairs.
ERROR_NOT_AVAILABLE: Final = "not_available"
ERROR_NO_REPLY: Final = "no_reply"
ERROR_NOT_CONNECTED: Final = "not_connected"
ERROR_ZONE_POWER_REFUSED: Final = "zone_power_refused"
ISSUE_CORE_CONFLICT: Final = "core_conflict"
