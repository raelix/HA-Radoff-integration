"""Class which represent the Radoff Coordinator."""

from dataclasses import dataclass
from datetime import timedelta
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    CONF_CLIENT_ID,
    CONF_PASSWORD,
    CONF_SCAN_INTERVAL,
    CONF_USERNAME,
)
from homeassistant.core import DOMAIN as HOMEASSISTANT_DOMAIN, HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import API, APIAuthError, Device
from .const import CONF_POOL_ID, CONF_POOL_REGION, DEFAULT_SCAN_INTERVAL

_LOGGER = logging.getLogger(__name__)


@dataclass
class APIData(dict[str, Any]):
    """Class to hold api data."""

    controller_name: str
    devices: list[Device]


class RadoffCoordinator(DataUpdateCoordinator):
    """The implementation of the Radoff coordinator."""

    data: APIData

    def __init__(self, hass: HomeAssistant, config_entry: ConfigEntry) -> None:
        """Initialize coordinator."""

        self.client_id = config_entry.data[CONF_CLIENT_ID]
        self.username = config_entry.data[CONF_USERNAME]
        self.password = config_entry.data[CONF_PASSWORD]
        self.pool_id = config_entry.data[CONF_POOL_ID]
        self.pool_region = config_entry.data[CONF_POOL_REGION]

        self.poll_interval = config_entry.options.get(
            CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL
        )

        super().__init__(
            hass,
            _LOGGER,
            name=f"{HOMEASSISTANT_DOMAIN} ({config_entry.unique_id})",
            update_method=self.async_update_data,
            update_interval=timedelta(seconds=self.poll_interval),
        )

        self.api = API(
            username=self.username,
            password=self.password,
            client_id=self.client_id,
            pool_id=self.pool_id,
            pool_region=self.pool_region,
        )

    async def async_update_data(self):
        """Fetch data from API endpoint."""

        _LOGGER.debug("Radoff async_update_data")
        try:
            if not self.api.connected:
                await self.hass.async_add_executor_job(self.api.connect)
            devices = await self.hass.async_add_executor_job(self.api.get_devices)

        except APIAuthError as err:
            _LOGGER.error(err)
            raise UpdateFailed(err) from err
        except Exception as err:
            raise UpdateFailed(f"Error communicating with API: {err}") from err

        return APIData(self.api.controller_name, devices)

    def get_device_by_id(self, device_type: str, device_id: str) -> Device | None:
        """Return device by device id."""

        _LOGGER.debug("Radoff get_device_by_id")
        try:
            for device in self.data.devices:
                if device.device_type == device_type and device.device_id == device_id:
                    return device
        except IndexError:
            return None
        return None
