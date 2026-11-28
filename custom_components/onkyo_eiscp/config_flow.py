"""Config flow (manual host, SSDP, reconfigure) and the options flow (volume)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from urllib.parse import urlparse

import probatio
from homeassistant.config_entries import (
    SOURCE_RECONFIGURE,
    ConfigEntry,
    ConfigEntryState,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlowWithReload,
)
from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.core import callback
from homeassistant.helpers.selector import (
    BooleanSelector,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
)

from .const import (
    CONF_MAX_VOLUME,
    CONF_RESTORE_VOLUME,
    CORE_DOMAIN,
    DEFAULT_PORT,
    DEFAULT_RESTORE_VOLUME,
    DOMAIN,
    ZONE_MAIN,
)
from .lib import EiscpClient, EiscpError
from .lib.codecs import DeviceInfo, parse_device_info

if TYPE_CHECKING:
    from homeassistant.helpers.service_info.ssdp import SsdpServiceInfo

    from .lib import Capabilities

_NRI_TIMEOUT = 8.0
_HEX_DB_OFFSET = 82.0

STEP_USER_SCHEMA = probatio.Schema(
    {
        probatio.Required(CONF_HOST): str,
        probatio.Required(CONF_PORT, default=DEFAULT_PORT): probatio.All(
            int, probatio.Range(min=1, max=65535)
        ),
    }
)


async def read_device_info(host: str, port: int) -> DeviceInfo:
    """Open one short connection, read ``NRI`` and close it again."""
    client = EiscpClient(host, port)
    await client.connect()
    try:
        xml = await client.query("NRI", timeout=_NRI_TIMEOUT)
    finally:
        await client.close()
    return parse_device_info(xml)


class OnkyoConfigFlow(ConfigFlow, domain=DOMAIN):
    """Add a receiver by host or from SSDP."""

    VERSION = 1

    def __init__(self) -> None:
        """Start without a discovered host."""
        self._host = ""
        self._port = DEFAULT_PORT
        self._info: DeviceInfo | None = None

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OnkyoOptionsFlow:  # noqa: ARG004
        """Return the options flow."""
        return OnkyoOptionsFlow()

    def _host_in_use(self, host: str) -> bool:
        """Return True when an entry already holds a connection to this host.

        The receiver closes the older connection when a second one opens from the same
        computer, so a loaded entry's host is never probed.
        """
        return any(
            entry.data.get(CONF_HOST) == host and entry.entry_id != self.context.get("entry_id")
            for entry in self._async_current_entries(include_ignore=False)
        )

    def _core_uses(self, host: str) -> bool:
        """Return True when the core Onkyo integration already uses this host."""
        return any(
            entry.data.get(CONF_HOST) == host
            for entry in self.hass.config_entries.async_entries(
                CORE_DOMAIN, include_ignore=False, include_disabled=False
            )
        )

    async def _interview(self, host: str, port: int) -> tuple[DeviceInfo | None, str | None]:
        """Read NRI; return the info or an error key."""
        try:
            return await read_device_info(host, port), None
        except EiscpError, OSError, TimeoutError:
            return None, "cannot_connect"

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Ask for the receiver's address."""
        errors: dict[str, str] = {}
        if user_input is not None:
            host = user_input[CONF_HOST].strip()
            port = user_input[CONF_PORT]
            if self._host_in_use(host):
                return self.async_abort(reason="already_configured")
            if self._core_uses(host):
                return self.async_abort(reason="core_conflict")
            info, error = await self._interview(host, port)
            if info is not None and not info.mac:
                error = "no_identity"
            if error or info is None:
                errors["base"] = error or "unknown"
            else:
                return await self._finish(info, host, port)
        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(STEP_USER_SCHEMA, user_input),
            errors=errors,
        )

    async def async_step_ssdp(self, discovery_info: SsdpServiceInfo) -> ConfigFlowResult:
        """Handle a receiver found by SSDP."""
        host = urlparse(discovery_info.ssdp_location or "").hostname
        if not host:
            return self.async_abort(reason="cannot_connect")
        if self._host_in_use(host):
            return self.async_abort(reason="already_configured")
        if self._core_uses(host):
            return self.async_abort(reason="core_conflict")
        info, error = await self._interview(host, DEFAULT_PORT)
        if info is None or not info.mac:
            return self.async_abort(reason=error or "cannot_connect")
        self._host, self._port, self._info = host, DEFAULT_PORT, info
        await self.async_set_unique_id(info.mac.lower())
        self._abort_if_unique_id_configured(updates={CONF_HOST: host})
        self.context["title_placeholders"] = {"name": _title(info)}
        return await self.async_step_confirm()

    async def async_step_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Confirm a discovered receiver."""
        if user_input is not None and self._info is not None:
            return self.async_create_entry(
                title=_title(self._info),
                data={CONF_HOST: self._host, CONF_PORT: self._port},
            )
        return self.async_show_form(
            step_id="confirm",
            description_placeholders={
                "name": _title(self._info) if self._info else "",
                "host": self._host,
            },
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Change the host or port of an existing entry."""
        entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            host = user_input[CONF_HOST].strip()
            port = user_input[CONF_PORT]
            unchanged = (host, port) == (entry.data[CONF_HOST], entry.data.get(CONF_PORT))
            info: DeviceInfo | None = None
            error: str | None = None
            if not unchanged and self._host_in_use(host):
                error = "already_configured"
            elif not unchanged:
                # The entry's own connection goes to the old host, so probing a new one is safe.
                info, error = await self._interview(host, port)
            if error:
                errors["base"] = error
            elif info is not None and entry.unique_id != info.mac.lower():
                errors["base"] = "wrong_device"
            else:
                return self.async_update_reload_and_abort(
                    entry, data_updates={CONF_HOST: host, CONF_PORT: port}
                )
        suggested = user_input or {
            CONF_HOST: entry.data[CONF_HOST],
            CONF_PORT: entry.data.get(CONF_PORT, DEFAULT_PORT),
        }
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=self.add_suggested_values_to_schema(STEP_USER_SCHEMA, suggested),
            errors=errors,
        )

    async def _finish(self, info: DeviceInfo, host: str, port: int) -> ConfigFlowResult:
        await self.async_set_unique_id(info.mac.lower())
        if self.source == SOURCE_RECONFIGURE:  # pragma: no cover - handled by its own step
            self._abort_if_unique_id_mismatch()
        else:
            self._abort_if_unique_id_configured(updates={CONF_HOST: host, CONF_PORT: port})
        return self.async_create_entry(title=_title(info), data={CONF_HOST: host, CONF_PORT: port})


def _title(info: DeviceInfo) -> str:
    return f"{info.brand.title()} {info.model}".strip()


# ----- options flow ----------------------------------------------------------------------------


class OnkyoOptionsFlow(OptionsFlowWithReload):
    """Set the volume limits; names, hiding and order live in the card's rename sheet."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Set the maximum volume and whether to put the volume back after power-on."""
        if self.config_entry.state is not ConfigEntryState.LOADED:
            return self.async_abort(reason="not_loaded")
        caps: Capabilities = self.config_entry.runtime_data.data.capabilities
        options = dict(self.config_entry.options)
        zone = caps.zone(ZONE_MAIN)
        top = zone.volume_max if zone else 100
        half_db = bool(zone and zone.half_db)
        if user_input is not None:
            raw = _to_raw(float(user_input[CONF_MAX_VOLUME]), half_db=half_db)
            raw = min(max(raw, 1), top)
            if raw >= top:
                options.pop(CONF_MAX_VOLUME, None)
            else:
                options[CONF_MAX_VOLUME] = raw
            options[CONF_RESTORE_VOLUME] = bool(user_input[CONF_RESTORE_VOLUME])
            return self.async_create_entry(data=options)
        current = int(options.get(CONF_MAX_VOLUME, top))
        selector = NumberSelector(
            NumberSelectorConfig(
                min=_from_raw(1, half_db=half_db),
                max=_from_raw(top, half_db=half_db),
                step=0.5 if half_db else 1,
                mode=NumberSelectorMode.BOX,
                unit_of_measurement="dB" if half_db else None,
            )
        )
        schema = probatio.Schema(
            {
                probatio.Required(CONF_MAX_VOLUME): selector,
                probatio.Required(CONF_RESTORE_VOLUME): BooleanSelector(),
            }
        )
        return self.async_show_form(
            step_id="init",
            data_schema=self.add_suggested_values_to_schema(
                schema,
                {
                    CONF_MAX_VOLUME: _from_raw(current, half_db=half_db),
                    CONF_RESTORE_VOLUME: options.get(CONF_RESTORE_VOLUME, DEFAULT_RESTORE_VOLUME),
                },
            ),
        )


def _from_raw(raw: int, *, half_db: bool) -> float:
    """Return the form value: dB on 0.5 dB models, else the raw step."""
    return raw / 2 - _HEX_DB_OFFSET if half_db else float(raw)


def _to_raw(value: float, *, half_db: bool) -> int:
    return round((value + _HEX_DB_OFFSET) * 2) if half_db else round(value)


__all__ = ["OnkyoConfigFlow", "OnkyoOptionsFlow", "read_device_info"]
