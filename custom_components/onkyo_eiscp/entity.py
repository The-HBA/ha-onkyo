"""The base entity: device, naming and state writes only when its codes changed."""

from __future__ import annotations

from contextlib import contextmanager
from typing import TYPE_CHECKING, ClassVar

from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    DOMAIN,
    ERROR_NO_REPLY,
    ERROR_NOT_AVAILABLE,
    ERROR_NOT_CONNECTED,
)
from .coordinator import EVERYTHING, OnkyoCoordinator
from .lib import ConnectionClosedError, NoReplyError, NotAvailableError

if TYPE_CHECKING:
    from collections.abc import Iterator


@contextmanager
def translated_errors() -> Iterator[None]:
    """Turn library errors into Home Assistant errors with translation keys (ARCHITECTURE.md C4)."""
    try:
        yield
    except NotAvailableError as err:
        raise HomeAssistantError(
            translation_domain=DOMAIN, translation_key=ERROR_NOT_AVAILABLE
        ) from err
    except NoReplyError as err:
        raise HomeAssistantError(translation_domain=DOMAIN, translation_key=ERROR_NO_REPLY) from err
    except ConnectionClosedError as err:
        raise HomeAssistantError(
            translation_domain=DOMAIN, translation_key=ERROR_NOT_CONNECTED
        ) from err


class OnkyoEntity(CoordinatorEntity[OnkyoCoordinator]):
    """An entity of one receiver and one zone."""

    _attr_has_entity_name = True
    #: Codes whose change makes this entity write its state (the coordinator pushes often).
    watched: ClassVar[frozenset[str]] = frozenset()

    def __init__(self, coordinator: OnkyoCoordinator, zone: str, key: str) -> None:
        """Set the identity: unique ID ``<mac>-<zone>-<key>``, one device per receiver."""
        super().__init__(coordinator)
        caps = coordinator.data.capabilities
        mac = caps.mac.lower()
        self._attr_translation_key = key
        self._attr_unique_id = f"{mac}-{zone}-{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, mac)},
            manufacturer=caps.brand.title(),
            model=caps.model,
            sw_version=caps.firmware or None,
            name=f"{caps.brand.title()} {caps.model}".strip(),
        )

    @property
    def available(self) -> bool:
        """Return True while the receiver is connected."""
        return self.coordinator.data.connected

    def _handle_coordinator_update(self) -> None:
        changed = self.coordinator.data.changed
        if EVERYTHING in changed or self.watched & changed or not self.watched:
            super()._handle_coordinator_update()
