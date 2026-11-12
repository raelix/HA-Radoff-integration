"""The radoff integration."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import logging
import re

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.helpers.device_registry import DeviceEntry
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .const import DOMAIN
from .coordinator import RadoffCoordinator

PLATFORMS: list[Platform] = [Platform.SENSOR, Platform.BINARY_SENSOR]

_LOGGER = logging.getLogger(__name__)

# Up to 1.0.0 entity unique IDs were built on the cloud v1 device UUID.
_LEGACY_UNIQUE_ID = re.compile(
    rf"^{DOMAIN}-[0-9a-f]{{8}}(?:-[0-9a-f]{{4}}){{3}}-[0-9a-f]{{12}}-(?P<suffix>.+)$",
    re.IGNORECASE,
)
# Sensor keys renamed by the cloud v2 API.
_LEGACY_SENSOR_KEYS = {"airqualityindex": "aqi_value"}


async def _async_migrate_unique_ids(
    hass: HomeAssistant, config_entry: ConfigEntry
) -> None:
    """Move UUID based unique IDs to the serial number used by the v2 API.

    The device registry has always been keyed on the serial number, so the
    serial of a legacy entity is read from the device it belongs to. This keeps
    entity IDs, history and automations when updating from 1.0.0.
    """
    device_registry = dr.async_get(hass)
    entity_registry = er.async_get(hass)

    @callback
    def _migrate(entity: er.RegistryEntry) -> dict[str, str] | None:
        match = _LEGACY_UNIQUE_ID.match(entity.unique_id)
        if match is None or entity.device_id is None:
            return None
        device = device_registry.async_get(entity.device_id)
        if device is None:
            return None
        serial = next(
            (ident[1] for ident in device.identifiers if ident[0] == DOMAIN), None
        )
        if not serial:
            return None

        suffix = match["suffix"]
        is_index = suffix.endswith("-index")
        key = suffix.removesuffix("-index")
        key = _LEGACY_SENSOR_KEYS.get(key, key)
        new_unique_id = f"{DOMAIN}-{serial}-{key}{'-index' if is_index else ''}"

        if entity_registry.async_get_entity_id(
            entity.domain, entity.platform, new_unique_id
        ):
            # Already re-created by 2.0.0: leave the legacy entity untouched.
            _LOGGER.debug(
                "Not migrating %s, %s already exists", entity.entity_id, new_unique_id
            )
            return None

        _LOGGER.info(
            "Migrating %s unique ID from %s to %s",
            entity.entity_id,
            entity.unique_id,
            new_unique_id,
        )
        return {"new_unique_id": new_unique_id}

    await er.async_migrate_entries(hass, config_entry.entry_id, _migrate)


@dataclass
class RuntimeData:
    """Class to hold your data."""

    coordinator: DataUpdateCoordinator
    cancel_update_listener: Callable


async def async_setup_entry(hass: HomeAssistant, config_entry: ConfigEntry) -> bool:
    """Set up Example Integration from a config entry."""
    _LOGGER.debug("Radoff async_setup_entry")

    hass.data.setdefault(DOMAIN, {})

    await _async_migrate_unique_ids(hass, config_entry)

    coordinator = RadoffCoordinator(hass, config_entry)

    await coordinator.async_config_entry_first_refresh()

    if not coordinator.api.connected:
        raise ConfigEntryNotReady

    cancel_update_listener = config_entry.add_update_listener(_async_update_listener)

    hass.data[DOMAIN][config_entry.entry_id] = RuntimeData(
        coordinator, cancel_update_listener
    )

    await hass.config_entries.async_forward_entry_setups(config_entry, PLATFORMS)

    return True


async def _async_update_listener(hass: HomeAssistant, config_entry):
    """Handle config options update."""
    await hass.config_entries.async_reload(config_entry.entry_id)


async def async_remove_config_entry_device(
    hass: HomeAssistant, config_entry: ConfigEntry, device_entry: DeviceEntry
) -> bool:
    """Delete device if selected from UI."""
    return True


async def async_unload_entry(hass: HomeAssistant, config_entry: ConfigEntry) -> bool:
    """Unload a config entry."""

    hass.data[DOMAIN][config_entry.entry_id].cancel_update_listener()

    unload_ok = await hass.config_entries.async_unload_platforms(
        config_entry, PLATFORMS
    )
    hass.data.pop(DOMAIN, None)

    return unload_ok
