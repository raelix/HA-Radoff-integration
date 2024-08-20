"""Class which represent the Radoff entity."""

import logging
from collections.abc import Callable
from enum import StrEnum
from numbers import Number
from typing import Any

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

INDEX_MAPPING: dict[str, dict[str, Any]] = {
    "tvoc": {
        "index": lambda val: "excellent"
        if val <= 100
        else "good"
        if val <= 200
        else "medium"
        if val <= 300
        else "poor"
        if val <= 400
        else "terrible"
    },
    "eco2": {
        "index": lambda val: "excellent"
        if val <= 500
        else "good"
        if val <= 1000
        else "medium"
        if val <= 1500
        else "poor"
        if val <= 2000
        else "terrible"
    },
    "pm10": {
        "index": lambda val: "excellent"
        if val <= 20
        else "good"
        if val <= 30
        else "medium"
        if val <= 40
        else "poor"
        if val <= 50
        else "terrible"
    },
    "pm25": {
        "index": lambda val: "excellent"
        if val <= 16
        else "good"
        if val <= 21
        else "medium"
        if val <= 26
        else "poor"
        if val <= 32
        else "terrible"
    },
    "pm1": {
        "index": lambda val: "excellent"
        if val <= 6
        else "good"
        if val <= 9
        else "medium"
        if val <= 12
        else "poor"
        if val <= 15
        else "terrible"
    },
    "internal_temperature": {
        "index": lambda val: "excellent"
        if val <= 18
        else "good"
        if val <= 27
        else "terrible"
    },
    "relative_humidity": {
        "index": lambda val: "excellent"
        if val <= 40
        else "good"
        if val <= 60
        else "terrible"
    },
}


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
                    is_index=False,
                    index_fn=None,
                )
            )
            if coordinator.data.generate_index and sensor.name in INDEX_MAPPING:
                index_obj = INDEX_MAPPING[sensor.name]
                sensors.append(  # noqa: PERF401
                    RadoffSensor(
                        sensor_key=sensor.name,
                        coordinator_context=coordinator,
                        device=device,
                        device_class=None,
                        friendly_name=sensor.friendly_name,
                        unit=None,
                        normalize_fn=sensor.normalize_fn,
                        is_index=True,
                        index_fn=index_obj["index"],
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
        device_class: SensorDeviceClass | None,
        friendly_name: str,
        normalize_fn: Callable[[Number], float | int],
        unit: type[StrEnum] | str | None,
        is_index: bool | None,
        index_fn: Callable[[Number], str] | None,
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
        self._is_index = is_index
        self._index_fn = index_fn

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
            # model_id=self.device.device_id,
        )

    @property
    def translation_key(self):
        """Return the translation key to translate the entity's name and states."""
        if not self._is_index:
            return self.sensor_key
        else:
            return f"{self.sensor_key}_index"

    @property
    def native_value(self) -> int | float:
        """Return the state of the entity."""
        val = None

        if self._normalize_fn is not None:
            val = float(self._normalize_fn(self.device.sensors[self.sensor_key].value))
        else:
            raw_val = self.device.sensors[self.sensor_key].value
            val = int(raw_val) if isinstance(raw_val, int) else float(raw_val)

        if self._is_index:
            return self._index_fn(val)
        else:
            return val

    @property
    def native_unit_of_measurement(self) -> str | None:
        """Return unit."""
        return None if self.unit is None else str(self.unit)

    @property
    def state_class(self) -> str | None:
        """Return state class."""
        if self._is_index:
            return None
        return SensorStateClass.MEASUREMENT

    @property
    def unique_id(self) -> str:
        """Return unique id."""
        if not self._is_index:
            return f"{DOMAIN}-{self.device.device_id}-{self.device.sensors[self.sensor_key].name}"
        else:
            return f"{DOMAIN}-{self.device.device_id}-{self.device.sensors[self.sensor_key].name}-index"
