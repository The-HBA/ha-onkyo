"""Config flow (manual host, SSDP, reconfigure) and the options flow (names, order, volume)."""

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
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
)

from .const import (
    CONF_HIDDEN,
    CONF_INPUT_ORDER,
    CONF_INPUTS,
    CONF_LISTENING_MODES,
    CONF_MAX_VOLUME,
    CONF_NAME,
    CONF_RESTORE_VOLUME,
    CORE_DOMAIN,
    DEFAULT_PORT,
    DEFAULT_RESTORE_VOLUME,
    DOMAIN,
    ZONE_MAIN,
)
from .lib import EiscpClient, EiscpError
from .lib.codecs import DeviceInfo, parse_device_info
from .naming import (
    input_name,
    ordered_input_codes,
    table_mode_name,
)

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
    def async_get_options_flow(config_entry: ConfigEntry) -> OnkyoOptionsFlow:
        """Return the options flow."""
        return OnkyoOptionsFlow(config_entry)

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


def _clean(section: dict[str, dict[str, Any]], code: str) -> None:
    """Drop the stored entry of ``code`` when it holds nothing."""
    entry = section.get(code)
    if entry is not None and not entry.get(CONF_NAME) and not entry.get(CONF_HIDDEN):
        del section[code]


class OnkyoOptionsFlow(OptionsFlowWithReload):
    """Rename and hide inputs and listening modes, order inputs, set the volume limits."""

    def __init__(self, entry: ConfigEntry) -> None:
        """Copy the stored options; nothing is saved until the user picks Save."""
        options = entry.options
        self._options: dict[str, Any] = {
            CONF_INPUTS: {
                code: dict(value) for code, value in options.get(CONF_INPUTS, {}).items()
            },
            CONF_LISTENING_MODES: {
                code: dict(value) for code, value in options.get(CONF_LISTENING_MODES, {}).items()
            },
        }
        for key in (CONF_INPUT_ORDER, CONF_MAX_VOLUME, CONF_RESTORE_VOLUME):
            if key in options:
                self._options[key] = options[key]
        self._editing = ""

    @property
    def _caps(self) -> Capabilities:
        return self.config_entry.runtime_data.data.capabilities

    @property
    def _values(self) -> dict[str, str]:
        return dict(self.config_entry.runtime_data.data.values)

    def _input_label(self, code: str) -> str:
        return input_name(self._caps, self._options, code)

    def _mode_label(self, code: str) -> str:
        # Names for the list are the user's or the table's, never the live IFA name.
        custom = self._options[CONF_LISTENING_MODES].get(code, {}).get(CONF_NAME)
        return str(custom) if custom else table_mode_name(code)

    async def async_step_init(self, _user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Show the menu (the entry must be loaded: the lists come from the receiver)."""
        if self.config_entry.state is not ConfigEntryState.LOADED:
            return self.async_abort(reason="not_loaded")
        return self.async_show_menu(
            step_id="init",
            menu_options=["inputs", "input_order", "listening_modes", "volume", "save"],
        )

    async def async_step_save(self, _user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Store the options and reload the entry."""
        return self.async_create_entry(data=self._options)

    # ----- inputs -----------------------------------------------------------------------------

    async def async_step_inputs(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Pick an input to rename or hide."""
        if user_input is not None:
            if code := user_input.get("input"):
                self._editing = code
                return await self.async_step_input_edit()
            return await self.async_step_init()
        choices = [
            SelectOptionDict(
                value=code,
                label=_with_flag(self._input_label(code), self._hidden(CONF_INPUTS, code)),
            )
            for code in ordered_input_codes(self._caps, self._options)
        ]
        schema = probatio.Schema(
            {
                probatio.Optional("input"): SelectSelector(
                    SelectSelectorConfig(options=choices, mode=SelectSelectorMode.DROPDOWN)
                )
            }
        )
        return self.async_show_form(step_id="inputs", data_schema=schema)

    async def async_step_input_edit(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Rename or hide one input."""
        code = self._editing
        errors: dict[str, str] = {}
        if user_input is not None:
            name = user_input.get(CONF_NAME, "").strip()
            default = next((item.name for item in self._caps.inputs if item.code == code), code)
            taken = {
                self._input_label(other)
                for other in (item.code for item in self._caps.inputs)
                if other != code
            }
            shown = name or default
            if shown in taken:
                errors[CONF_NAME] = "name_in_use"
            else:
                stored = self._options[CONF_INPUTS].setdefault(code, {})
                stored[CONF_NAME] = "" if shown == default else shown
                stored[CONF_HIDDEN] = bool(user_input.get(CONF_HIDDEN, False))
                _clean(self._options[CONF_INPUTS], code)
                return await self.async_step_inputs()
        suggested = user_input or {
            CONF_NAME: self._input_label(code),
            CONF_HIDDEN: self._hidden(CONF_INPUTS, code),
        }
        return self.async_show_form(
            step_id="input_edit",
            data_schema=self.add_suggested_values_to_schema(_EDIT_SCHEMA, suggested),
            errors=errors,
            description_placeholders={"code": code},
        )

    async def async_step_input_order(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Pick the inputs in the order the source list shows them."""
        receiver_order = [item.code for item in self._caps.inputs]
        if user_input is not None:
            chosen = list(user_input.get(CONF_INPUT_ORDER, []))
            rest = [code for code in receiver_order if code not in chosen]
            if chosen + rest == receiver_order:
                self._options.pop(CONF_INPUT_ORDER, None)
            else:
                self._options[CONF_INPUT_ORDER] = chosen
            return await self.async_step_init()
        choices = [
            SelectOptionDict(value=code, label=self._input_label(code))
            for code in ordered_input_codes(self._caps, self._options)
        ]
        schema = probatio.Schema(
            {
                probatio.Required(CONF_INPUT_ORDER): SelectSelector(
                    SelectSelectorConfig(
                        options=choices,
                        multiple=True,
                        sort=False,
                        mode=SelectSelectorMode.DROPDOWN,
                    )
                )
            }
        )
        return self.async_show_form(
            step_id="input_order",
            data_schema=self.add_suggested_values_to_schema(
                schema, {CONF_INPUT_ORDER: ordered_input_codes(self._caps, self._options)}
            ),
        )

    # ----- listening modes ----------------------------------------------------------------------

    async def async_step_listening_modes(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Pick a listening mode to rename or hide."""
        if user_input is not None:
            if code := user_input.get("mode"):
                self._editing = code
                return await self.async_step_mode_edit()
            return await self.async_step_init()
        choices = [
            SelectOptionDict(
                value=code,
                label=_with_flag(self._mode_label(code), self._hidden(CONF_LISTENING_MODES, code)),
            )
            for code in self._caps.listening_modes
        ]
        schema = probatio.Schema(
            {
                probatio.Optional("mode"): SelectSelector(
                    SelectSelectorConfig(options=choices, mode=SelectSelectorMode.DROPDOWN)
                )
            }
        )
        return self.async_show_form(step_id="listening_modes", data_schema=schema)

    async def async_step_mode_edit(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Rename or hide one listening mode."""
        code = self._editing
        errors: dict[str, str] = {}
        if user_input is not None:
            name = user_input.get(CONF_NAME, "").strip()
            default = table_mode_name(code)
            taken = {
                self._mode_label(other) for other in self._caps.listening_modes if other != code
            }
            shown = name or default
            if shown in taken:
                errors[CONF_NAME] = "name_in_use"
            else:
                stored = self._options[CONF_LISTENING_MODES].setdefault(code, {})
                stored[CONF_NAME] = "" if shown == default else shown
                stored[CONF_HIDDEN] = bool(user_input.get(CONF_HIDDEN, False))
                _clean(self._options[CONF_LISTENING_MODES], code)
                return await self.async_step_listening_modes()
        suggested = user_input or {
            CONF_NAME: self._mode_label(code),
            CONF_HIDDEN: self._hidden(CONF_LISTENING_MODES, code),
        }
        return self.async_show_form(
            step_id="mode_edit",
            data_schema=self.add_suggested_values_to_schema(_EDIT_SCHEMA, suggested),
            errors=errors,
            description_placeholders={"code": code},
        )

    # ----- volume -------------------------------------------------------------------------------

    async def async_step_volume(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Set the maximum volume and whether to put the volume back after power-on."""
        zone = self._caps.zone(ZONE_MAIN)
        top = zone.volume_max if zone else 100
        half_db = bool(zone and zone.half_db)
        if user_input is not None:
            raw = _to_raw(float(user_input[CONF_MAX_VOLUME]), half_db=half_db)
            raw = min(max(raw, 1), top)
            if raw >= top:
                self._options.pop(CONF_MAX_VOLUME, None)
            else:
                self._options[CONF_MAX_VOLUME] = raw
            self._options[CONF_RESTORE_VOLUME] = bool(user_input[CONF_RESTORE_VOLUME])
            return await self.async_step_init()
        current = int(self._options.get(CONF_MAX_VOLUME, top))
        shown = _from_raw(current, half_db=half_db)
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
            step_id="volume",
            data_schema=self.add_suggested_values_to_schema(
                schema,
                {
                    CONF_MAX_VOLUME: shown,
                    CONF_RESTORE_VOLUME: self._options.get(
                        CONF_RESTORE_VOLUME, DEFAULT_RESTORE_VOLUME
                    ),
                },
            ),
        )

    def _hidden(self, section: str, code: str) -> bool:
        return bool(self._options[section].get(code, {}).get(CONF_HIDDEN, False))


_EDIT_SCHEMA = probatio.Schema(
    {
        probatio.Optional(CONF_NAME): TextSelector(),
        probatio.Optional(CONF_HIDDEN, default=False): BooleanSelector(),
    }
)


def _with_flag(label: str, hidden: bool) -> str:  # noqa: FBT001
    return f"{label} (hidden)" if hidden else label


def _from_raw(raw: int, *, half_db: bool) -> float:
    """Return the form value: dB on 0.5 dB models, else the raw step."""
    return raw / 2 - _HEX_DB_OFFSET if half_db else float(raw)


def _to_raw(value: float, *, half_db: bool) -> int:
    return round((value + _HEX_DB_OFFSET) * 2) if half_db else round(value)


__all__ = ["OnkyoConfigFlow", "OnkyoOptionsFlow", "read_device_info"]
