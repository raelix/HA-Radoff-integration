"""Class which represent the Radoff API."""

from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
import logging
from numbers import Number
from typing import Any

from pycognito.aws_srp import AWSSRP
import requests

from homeassistant.components.sensor import DEVICE_CLASS_UNITS, SensorDeviceClass
from homeassistant.const import UnitOfPressure, UnitOfTemperature

_LOGGER = logging.getLogger(__name__)

DEVICE_TYPES = ["Now+"]


@dataclass
class RadoffSensor:
    """Dataclass to store the entity data."""

    name: str
    value: Number
    device_class: SensorDeviceClass
    friendly_name: str
    unit: type[StrEnum] | str | None
    normalize_fn: Callable[[Number], float | int]


@dataclass
class Device:
    """API device."""

    device_id: str
    device_serial: str
    device_type: str
    name: str
    sensors: dict[str, RadoffSensor]


MAPPING: dict[str, dict[str, dict[str, Any]]] = {
    "data": {
        "tvoc": {
            "deviceClass": SensorDeviceClass.VOLATILE_ORGANIC_COMPOUNDS,
            "friendlyName": "VOC",
            "unit": list(
                DEVICE_CLASS_UNITS[SensorDeviceClass.VOLATILE_ORGANIC_COMPOUNDS]
            )[0],
        },
        "eco2": {
            "deviceClass": SensorDeviceClass.CO2,
            "friendlyName": "Co2",
            "unit": list(DEVICE_CLASS_UNITS[SensorDeviceClass.CO2])[0],
        },
        "pm10": {
            "deviceClass": SensorDeviceClass.PM10,
            "friendlyName": "PM10",
            "unit": list(DEVICE_CLASS_UNITS[SensorDeviceClass.PM10])[0],
        },
        "pm25": {
            "deviceClass": SensorDeviceClass.PM25,
            "friendlyName": "PM2.5",
            "unit": list(DEVICE_CLASS_UNITS[SensorDeviceClass.PM25])[0],
        },
        "pm1": {
            "deviceClass": SensorDeviceClass.PM1,
            "friendlyName": "PM1",
            "unit": list(DEVICE_CLASS_UNITS[SensorDeviceClass.PM1])[0],
        },
        "internal_temperature": {
            "deviceClass": SensorDeviceClass.TEMPERATURE,
            "friendlyName": "Temperature",
            "unit": UnitOfTemperature.CELSIUS,
            "normalize_fn": lambda value: round(float(value) * 0.00835, 1),
        },
        "relative_humidity": {
            "deviceClass": SensorDeviceClass.HUMIDITY,
            "friendlyName": "Humidity",
            "unit": list(DEVICE_CLASS_UNITS[SensorDeviceClass.HUMIDITY])[0],
        },
        "pressure": {
            "deviceClass": SensorDeviceClass.PRESSURE,
            "friendlyName": "Pressure",
            "unit": UnitOfPressure.PA,
        },
        "airqualityindex": {
            "deviceClass": SensorDeviceClass.AQI,
            "friendlyName": "Air Quality",
            "unit": None,
        },
    },
    "aggregatedData": {
        "airqualityindex": {
            "deviceClass": SensorDeviceClass.AQI,
            "friendlyName": "Air Quality",
            "unit": None,
        },
    },
}


class API:
    """API platform."""

    BASE_DOMAIN = "https://api.iot.radoff.life/api/v1/core"
    PARENT_DOMAIN = "94e966f9-e0b2-11ec-a450-02ab88ac9cd7"
    DEFAULT_TIMEOUT = 50

    def __init__(
        self,
        username: str,
        password: str,
        client_id: str,
        pool_id: str,
        pool_region: str,
    ) -> None:
        """Initialise."""
        self.username = username
        self.password = password
        self.client_id = client_id
        self.pool_id = pool_id
        self.pool_region = pool_region
        self.connected: bool = False
        self.domain: str = ""
        self.tokens: dict = {}

    @property
    def controller_name(self) -> str:
        """Return the name of the controller."""
        return "cloud_poller"

    def connect(self) -> bool:
        """Connect to api."""
        if self.username != "" and self.password != "" and self.client_id != "":
            connection = AWSSRP(
                username=self.username,
                password=self.password,
                pool_id=self.pool_id,
                client_id=self.client_id,
                pool_region=self.pool_region,
            )
            auth_data = connection.authenticate_user()
            if auth_data is not None and "AuthenticationResult" in auth_data:
                self.tokens = auth_data["AuthenticationResult"]
                self.connected = True
                domain = self._get_domain(self._get_bearer_token())
                if domain is not None and domain != "":
                    self.domain = domain
                else:
                    raise DomainNotFoundError("Error domain not found.")
            return True
        raise APIAuthError("Error connecting to api. Invalid authentication data.")

    def disconnect(self) -> bool:
        """Disconnect from api."""
        self.connected = False
        self.tokens = {}
        self.domain = ""
        return True

    def get_devices(self) -> list[Device]:
        """Get devices on api."""
        device_list: list[Device] = []

        url = f"{self.BASE_DOMAIN}/data/devices/search"
        post_obj = {"filter": {}, "take": 99}

        response = requests.post(
            url,
            headers=self._get_headers(
                bearer_token=self._get_bearer_token(), x_domain=self.domain
            ),
            json=post_obj,
            timeout=self.DEFAULT_TIMEOUT,
        )

        self._check_response_status(response=response)

        devices = response.json()["devices"]

        for device in devices:
            if "deviceTypeName" in device and device["deviceTypeName"] in DEVICE_TYPES:
                sensors = self._get_data(device["id"])
                device_list.append(
                    Device(
                        device_id=device["id"],
                        device_serial=device["serial"],
                        device_type=device["deviceTypeName"],
                        name=device["name"],
                        sensors=sensors,
                    )
                )
        return device_list

    def _get_data(self, device_id: str):
        sensors: dict[str, RadoffSensor] = {}

        url = f"{self.BASE_DOMAIN}/data/devices/{device_id}"
        response = requests.get(
            url,
            headers=self._get_headers(
                bearer_token=self._get_bearer_token(), x_domain=self.domain
            ),
            timeout=self.DEFAULT_TIMEOUT,
        )

        self._check_response_status(response=response)

        result = response.json()

        _LOGGER.debug("Radoff poll data are: %s", result["data"])

        for k, v in MAPPING.items():
            if k in result["data"]:
                for obj in result["data"][k]:
                    pn = obj["propertyName"]

                    if "value" in obj:
                        av = obj["value"]
                    else:
                        av = obj["aggregationValue"]

                    if pn in v:
                        obj_map = v[pn]
                        fn = obj_map.get("normalize_fn", None)
                        sensors[pn] = RadoffSensor(
                            name=pn,
                            value=av,
                            device_class=obj_map["deviceClass"],
                            friendly_name=obj_map["friendlyName"],
                            unit=obj_map["unit"],
                            normalize_fn=fn,
                        )

        return sensors

    def _get_bearer_token(self):
        if self.tokens is not None and "IdToken" in self.tokens:
            return self.tokens["IdToken"]
        raise BearerTokenNotFoundError("Error retrieving bearer token.")

    def _get_headers(self, bearer_token: str, x_domain: str):
        return {
            "user-agent": "Dart/3.5 (dart:io)",
            "x-domain": x_domain,
            "accept-encoding": "gzip",
            "host": "api.iot.radoff.life",
            "authorization": "Bearer " + bearer_token,
            "content-type": "application/json",
        }

    def _get_domain(self, bearer_token):
        """Get available domain."""
        url = f"{self.BASE_DOMAIN}/auth/user/me/domains"

        response = requests.get(
            url,
            headers=self._get_headers(
                bearer_token=bearer_token, x_domain=self.PARENT_DOMAIN
            ),
            timeout=self.DEFAULT_TIMEOUT,
        )
        resp_json = response.json()
        for domain in resp_json["domains"]:
            if domain["parentDomainId"] == self.PARENT_DOMAIN:
                return domain["id"]
        return None

    def _check_response_status(self, response: requests.Response):
        if response.status_code == 200:
            return True
        self.disconnect()
        self.connect()
        raise APIAuthError("An error occurred while fetching new data")


class APIAuthError(Exception):
    """Exception class for auth error."""


class APIConnectionError(Exception):
    """Exception class for connection error."""


class DomainNotFoundError(Exception):
    """Exception class for domain not found error."""


class BearerTokenNotFoundError(Exception):
    """Exception class for bearer token not found/available."""
