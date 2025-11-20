"""Class which represent the Radoff entity."""

import logging
from collections.abc import Callable
from collections import deque
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

# Threshold definitions for outlier detection (sensor_key -> max_allowed_change_per_update)
OUTLIER_THRESHOLDS: dict[str, float] = {
    "internal_temperature": 5.0,  # Max 5°C change between readings
    "tvoc": 150.0,  # Max 150 V-lx change
    "eco2": 500.0,  # Max 500 ppm change
    "relative_humidity": 15.0,  # Max 15% change
    "pm1": 50.0,
    "pm25": 50.0,
    "pm10": 50.0,
    "pressure": 1000.0,  # Max 1000 Pa change
}

# Special configuration for detecting drops to zero/near-zero values
# This catches sensor errors where value drops to 0 from normal readings
ZERO_DROP_CONFIG: dict[str, dict[str, float]] = {
    "tvoc": {
        "low_threshold": 1.0,     # Values below this are considered "zero"
        "normal_threshold": 20.0,  # Previous value must be above this to trigger zero-drop detection
    }
}

# Shared filtered values storage per device
# Structure: {device_id: {sensor_key: filtered_value_or_None}}
_FILTERED_VALUES: dict[str, dict[str, float | int | None]] = {}


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
        # Initialize filtered values storage for this device
        if device.device_id not in _FILTERED_VALUES:
            _FILTERED_VALUES[device.device_id] = {}

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
        # History buffer for outlier detection (stores last 3 values) - ONLY for base sensors
        self._value_history: deque = deque(maxlen=3) if not is_index else None
        self._last_valid_value: float | int | None = None if not is_index else None

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

    def _calculate_median(self, values: list) -> float | int:
        """Calculate median of values."""
        sorted_values = sorted(values)
        n = len(sorted_values)
        if n == 0:
            return None
        elif n % 2 == 1:
            # Odd number of values
            return sorted_values[n // 2]
        else:
            # Even number of values - average of middle two
            mid1 = sorted_values[n // 2 - 1]
            mid2 = sorted_values[n // 2]
            if isinstance(sorted_values[0], int):
                return int((mid1 + mid2) / 2)
            else:
                return (mid1 + mid2) / 2

    def _is_outlier_detected(self, current_value: float | int) -> bool:
        """Detect if value change exceeds threshold (outlier detection with hybrid method)."""
        if self._last_valid_value is None:
            # No previous value to compare
            return False
        # Check if this sensor has an outlier threshold defined
        if self.sensor_key not in OUTLIER_THRESHOLDS:
            # No threshold defined, accept all values
            return False

        # HYBRID METHOD: Check for zero-drop condition first (sensor-specific)
        if self.sensor_key in ZERO_DROP_CONFIG:
            config = ZERO_DROP_CONFIG[self.sensor_key]
            low_threshold = config["low_threshold"]
            normal_threshold = config["normal_threshold"]

            # If current value drops to near-zero AND previous value was normal
            # This catches sensor errors like TVOC dropping from 70 to 0
            if current_value < low_threshold and self._last_valid_value > normal_threshold:
                _LOGGER.warning(
                    "Zero-drop outlier detected for %s (%s): value dropped from %s to %s (below %s, was above %s)",
                    self.friendly_name,
                    self.sensor_key,
                    self._last_valid_value,
                    current_value,
                    low_threshold,
                    normal_threshold
                )
                return True

        # Standard threshold check for all other outliers
        threshold = OUTLIER_THRESHOLDS[self.sensor_key]
        change = abs(current_value - self._last_valid_value)
        if change > threshold:
            _LOGGER.warning(
                "Threshold outlier detected for %s (%s): value changed from %s to %s (threshold: %s)",
                self.friendly_name,
                self.sensor_key,
                self._last_valid_value,
                current_value,
                threshold
            )
            return True
        return False

    def _get_filtered_base_value(self) -> float | int | None:
        """Get the current filtered value from shared storage."""
        device_values = _FILTERED_VALUES.get(self.device.device_id, {})
        return device_values.get(self.sensor_key)

    def _store_filtered_value(self, value: float | int | None) -> None:
        """Store filtered value in shared storage for index sensors to use."""
        if self.device.device_id not in _FILTERED_VALUES:
            _FILTERED_VALUES[self.device.device_id] = {}
        _FILTERED_VALUES[self.device.device_id][self.sensor_key] = value

    @property
    def native_value(self) -> int | float | str | None:
        """Return the state of the entity."""
        # INDEX SENSOR - use filtered value from base sensor
        if self._is_index:
            filtered_val = self._get_filtered_base_value()
            # If base sensor filtered out the value (None), don't send index either
            if filtered_val is None:
                _LOGGER.debug(
                    "Index sensor %s: base value was filtered out, returning None",
                    self.sensor_key
                )
                return None
            # Apply index function to filtered value
            return self._index_fn(filtered_val)
        # BASE SENSOR - apply outlier detection and store result
        # Get raw value
        val = None

        if self._normalize_fn is not None:
            val = float(self._normalize_fn(self.device.sensors[self.sensor_key].value))
        else:
            raw_val = self.device.sensors[self.sensor_key].value
            val = int(raw_val) if isinstance(raw_val, int) else float(raw_val)
        # Check for outlier detection
        if self._is_outlier_detected(val):
            # Outlier detected - use median of history as replacement
            if len(self._value_history) > 0:
                median_value = self._calculate_median(list(self._value_history))
                _LOGGER.info(
                    "Using median value %s for %s instead of outlier %s",
                    median_value,
                    self.sensor_key,
                    val
                )
                # Don't add outlier to history
                # Store median value for index sensor
                self._store_filtered_value(median_value)
                self._last_valid_value = median_value
                return median_value
            elif self._last_valid_value is not None:
                # No history but have last valid value
                _LOGGER.info(
                    "Using last valid value %s for %s instead of outlier %s",
                    self._last_valid_value,
                    self.sensor_key,
                    val
                )
                # Store last valid value for index sensor
                self._store_filtered_value(self._last_valid_value)
                return self._last_valid_value
            else:
                # No history and no last valid value - skip this reading
                _LOGGER.warning(
                    "Outlier detected for %s but no previous valid value, skipping this reading",
                    self.sensor_key
                )
                # Store None to signal index sensor to also skip
                self._store_filtered_value(None)
                return None
        # No outlier - use raw value directly
        # Add to history for future outlier detection
        self._value_history.append(val)
        self._last_valid_value = val
        # Store value for index sensor to use
        self._store_filtered_value(val)
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
