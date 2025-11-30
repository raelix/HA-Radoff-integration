"""Class which represent the Radoff entity with outlier filtering."""

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

# Outlier filter configuration
OUTLIER_FILTER_CONFIG = {
    "internal_temperature": {
        "spike_threshold": 5.0,  # °C
        "drop_threshold": None,
        "enabled": True,
    },
    "eco2": {
        "spike_threshold": 500,  # ppm
        "drop_threshold": None,
        "enabled": True,
    },
    "tvoc": {
        "spike_threshold": 200,  # V-lx
        "drop_threshold": 5.0,   # V-lx
        "enabled": True,
    },
}

# Shared state for outlier filter (across sensor instances)
# Key: f"{device_id}_{sensor_key}"
# Value: {"last_valid": float, "count": int}
_FILTER_STATE = {}

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


def _get_filter_state_key(device_id: str, sensor_key: str) -> str:
    """Generate unique key for filter state."""
    return f"{device_id}_{sensor_key}"


def _get_last_valid_value(device_id: str, sensor_key: str) -> float | None:
    """Get last valid value from shared state."""
    key = _get_filter_state_key(device_id, sensor_key)
    state = _FILTER_STATE.get(key)
    return state["last_valid"] if state else None


def _set_last_valid_value(device_id: str, sensor_key: str, value: float) -> None:
    """Set last valid value in shared state."""
    key = _get_filter_state_key(device_id, sensor_key)
    if key not in _FILTER_STATE:
        _FILTER_STATE[key] = {"last_valid": value, "count": 0}
    else:
        _FILTER_STATE[key]["last_valid"] = value


def _increment_filter_count(device_id: str, sensor_key: str) -> int:
    """Increment filter activation counter and return new count."""
    key = _get_filter_state_key(device_id, sensor_key)
    if key not in _FILTER_STATE:
        _FILTER_STATE[key] = {"last_valid": None, "count": 1}
    else:
        _FILTER_STATE[key]["count"] = _FILTER_STATE[key].get("count", 0) + 1
    return _FILTER_STATE[key]["count"]

def _reset_consecutive_count(device_id: str, sensor_key: str) -> None:
    """Reset the consecutive outlier counter."""
    key = _get_filter_state_key(device_id, sensor_key)
    if key in _FILTER_STATE:
        _FILTER_STATE[key]["consecutive"] = 0

def _increment_consecutive_count(device_id: str, sensor_key: str) -> int:
    """Increment consecutive outlier counter and return new count."""
    key = _get_filter_state_key(device_id, sensor_key)
    if key not in _FILTER_STATE:
        # Initialisieren, falls noch nicht vorhanden
        _FILTER_STATE[key] = {"last_valid": None, "count": 0, "consecutive": 1}
    else:
        _FILTER_STATE[key]["consecutive"] = _FILTER_STATE[key].get("consecutive", 0) + 1
    return _FILTER_STATE[key]["consecutive"]

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
    """A sensor representing the radoff sensor entity with outlier filtering."""

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

        # Outlier filter enabled for this sensor type?
        self._outlier_filter_enabled = (
            sensor_key in OUTLIER_FILTER_CONFIG 
            and OUTLIER_FILTER_CONFIG[sensor_key]["enabled"]
        )

    def _is_outlier(self, current_value: float | int) -> bool:
        """
        Check if current value is an outlier (spike or drop).
        Returns True if the value should be filtered out.
        Uses shared state across sensor instances.
        """
        if not self._outlier_filter_enabled:
            return False

        last_valid = _get_last_valid_value(self.device.device_id, self.sensor_key)
        if last_valid is None:
            return False

        config = OUTLIER_FILTER_CONFIG[self.sensor_key]
        spike_threshold = config.get("spike_threshold")
        drop_threshold = config.get("drop_threshold")

        # Check for spike (sudden large increase)
        if spike_threshold is not None:
            jump = current_value - last_valid
            if abs(jump) > spike_threshold:
                _LOGGER.debug(
                    "Outlier detected in %s: spike from %.2f to %.2f (threshold: %.2f)",
                    self.sensor_key,
                    last_valid,
                    current_value,
                    spike_threshold,
                )
                return True

        # Check for drop (sudden fall to near-zero)
        if drop_threshold is not None:
            if current_value <= drop_threshold and last_valid > drop_threshold * 1.5:
                _LOGGER.debug(
                    "Outlier detected in %s: drop from %.2f to %.2f (threshold: %.2f)",
                    self.sensor_key,
                    last_valid,
                    current_value,
                    drop_threshold,
                )
                return True
                
        _LOGGER.debug(
            "No outlier detected in %s: %.2f to %.2f",
            self.sensor_key,
            last_valid,
            current_value,
        )
        return False

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
    def native_value(self) -> int | float | str:
        """Return the state of the entity with outlier filtering.

        The filter uses shared state so both main and index sensors
        use the same filtered value.
        """
        val = None

        if self._normalize_fn is not None:
            val = float(self._normalize_fn(self.device.sensors[self.sensor_key].value))
        else:
            raw_val = self.device.sensors[self.sensor_key].value
            val = int(raw_val) if isinstance(raw_val, int) else float(raw_val)

        # Apply outlier filter (uses shared state)
        if self._outlier_filter_enabled and not self._is_index:
            last_valid = _get_last_valid_value(self.device.device_id, self.sensor_key)

            # Initialize if first value
            if last_valid is None:
                _set_last_valid_value(self.device.device_id, self.sensor_key, val)
                _reset_consecutive_count(self.device.device_id, self.sensor_key)

            elif self._is_outlier(val):
                # Outlier detected
                consecutive = _increment_consecutive_count(self.device.device_id, self.sensor_key)
                
                # if three consecutive outliers occur, we accept the value as the new truth
                if consecutive >= 3:
                    _LOGGER.warning(
                        "Outlier persisted for %d readings in %s. Accepting new value %.2f as valid (prev: %.2f).",
                        consecutive,
                        self.sensor_key,
                        val,
                        last_valid
                    )
                    _set_last_valid_value(self.device.device_id, self.sensor_key, val)
                    _reset_consecutive_count(self.device.device_id, self.sensor_key)
                    # val ist nun der neue korrekte Wert
                else:
                    # Return last valid value instead of outlier
                    filter_count = _increment_filter_count(self.device.device_id, self.sensor_key)
                    _LOGGER.info(
                        "Filtering outlier for %s%s: using %.2f instead of %.2f (filter activation #%d, consecutive #%d)",
                        self.sensor_key,
                        "_index" if self._is_index else "",
                        last_valid,
                        val,
                        filter_count,
                        consecutive
                    )
                    val = last_valid
            else:
                # Valid value - update last valid and reset counter
                if not self._is_index:
                    _set_last_valid_value(self.device.device_id, self.sensor_key, val)
                    _reset_consecutive_count(self.device.device_id, self.sensor_key)

        # For index sensors, compute index from the (potentially filtered) value
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
