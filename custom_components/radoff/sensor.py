"""Class which represent the Radoff entity."""

from collections.abc import Callable
from enum import StrEnum
import logging
from numbers import Number

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .api import Device
from .const import DOMAIN
from .coordinator import RadoffCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Sensors."""
    _LOGGER.debug("Radoff async_setup_entry")

    coordinator: RadoffCoordinator = hass.data[DOMAIN][
        config_entry.entry_id
    ].coordinator

    sensors = []
    for device in coordinator.data.devices:
        for sensor in device.sensors.values():
            sensors.append(  # noqa: PERF401
                RadoffSensor(
                    sensor_key=sensor.name,
                    coordinator_context=coordinator,
                    device=device,
                    device_class=sensor.device_class,
                    friendly_name=sensor.friendly_name,
                    unit=sensor.unit,
                    normalize_fn=sensor.normalize_fn,
                )
            )

    # Create the sensors.
    async_add_entities(sensors)


class RadoffSensor(CoordinatorEntity, SensorEntity):
    """A sensor representing the radoff sensor entity."""

    _attr_has_entity_name = True

    def __init__(
        self,
        sensor_key: str,
        device: Device,
        coordinator_context: RadoffCoordinator,
        device_class: SensorDeviceClass,
        friendly_name: str,
        normalize_fn: Callable[[Number], float | int],
        unit: type[StrEnum] | str | None,
    ) -> None:
        """Initialize the sensor."""

        super().__init__(coordinator_context, context=sensor_key)
        self.device = device
        self.sensor_key = sensor_key
        self.friendly_name = friendly_name
        self.unit = unit
        self._attr_device_class = device_class
        self._normalize_fn = normalize_fn
        self.coordinator_context = coordinator_context

    @callback
    def _handle_coordinator_update(self) -> None:
        """Update sensor with latest data from coordinator."""
        _LOGGER.debug("Device: %s", self.device)
        self.device = self.coordinator_context.get_device_by_id(
            self.device.device_type, self.device.device_id
        )
        self.async_write_ha_state()

    @property
    def device_info(self) -> DeviceInfo:
        """Return the device info."""
        return DeviceInfo(
            identifiers={(DOMAIN, self.device.device_serial)},
            name=self.device.name,
            manufacturer="Radoff",
            model=self.device.device_type,
            model_id=self.device.device_id,
        )

    @property
    def translation_key(self):
        """Return the translation key to translate the entity's name and states."""
        return self.sensor_key

    # @property
    # def device_class(self) -> str:
    #     """Return device class."""
    #     return self._attr_device_class

    @property
    def native_value(self) -> int | float:
        """Return the state of the entity."""
        if self._normalize_fn is not None:
            return float(self._normalize_fn(self.device.sensors[self.sensor_key].value))
        val = self.device.sensors[self.sensor_key].value
        return int(val) if isinstance(val, int) else float(val)

    @property
    def native_unit_of_measurement(self) -> str | None:
        """Return unit."""
        return None if self.unit is None else str(self.unit)

    @property
    def state_class(self) -> str | None:
        """Return state class."""
        return SensorStateClass.MEASUREMENT

    @property
    def unique_id(self) -> str:
        """Return unique id."""
        return f"{DOMAIN}-{self.device.device_id}-{self.device.sensors[self.sensor_key].name}"

    # @property
    # def extra_state_attributes(self):
    #     """Return the extra state attributes."""
    #     attrs = {}
    #     attrs["extra_info"] = "Extra Info"
    #     return attrs
