"""Binary sensors for the radoff integration."""

import logging

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .api import Device
from .const import DOMAIN
from .coordinator import RadoffCoordinator
from .sensor import device_info_for

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the binary sensors."""
    coordinator: RadoffCoordinator = hass.data[DOMAIN][
        config_entry.entry_id
    ].coordinator

    async_add_entities(
        RadoffCloudConnectionSensor(coordinator, device)
        for device in coordinator.data.devices
    )


class RadoffCloudConnectionSensor(CoordinatorEntity, BinarySensorEntity):
    """Whether the device is currently connected to the Radoff cloud."""

    _attr_has_entity_name = True
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_translation_key = "cloud_connection"

    def __init__(self, coordinator: RadoffCoordinator, device: Device) -> None:
        """Initialize the binary sensor."""
        super().__init__(coordinator)
        self.device = device
        self._attr_unique_id = f"{DOMAIN}-{device.device_id}-cloud_connection"
        self._attr_device_info = device_info_for(device)

    @callback
    def _handle_coordinator_update(self) -> None:
        """Update with latest data from coordinator."""
        device = self.coordinator.get_device_by_id(
            self.device.device_type, self.device.device_id
        )
        if device is not None:
            self.device = device
        self.async_write_ha_state()

    @property
    def available(self) -> bool:
        """Only available when the API reports a connection flag."""
        return super().available and self.device.connected is not None

    @property
    def is_on(self) -> bool | None:
        """Return True when the device is connected to the cloud."""
        return self.device.connected
