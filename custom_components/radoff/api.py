"""Class which represents the Radoff v2 API."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
import logging
from numbers import Number
import time
from typing import Any

from pycognito.aws_srp import AWSSRP
import requests
from requests.adapters import HTTPAdapter, Retry

from homeassistant.components.sensor import SensorDeviceClass
from homeassistant.const import (
    CONCENTRATION_MICROGRAMS_PER_CUBIC_METER,
    CONCENTRATION_PARTS_PER_MILLION,
    PERCENTAGE,
    UnitOfPressure,
    UnitOfTemperature,
)
from homeassistant.util import dt as dt_util

_LOGGER = logging.getLogger(__name__)

DEVICE_TYPES = ["nowplus"]

# v2 delivers the telemetry already as a flat object with proper types and
# units, so a plain passthrough is sufficient here.
MAPPING: dict[str, dict[str, Any]] = {
    "tvoc": {
        "deviceClass": SensorDeviceClass.VOLATILE_ORGANIC_COMPOUNDS,
        "friendlyName": "VOC",
        "unit": CONCENTRATION_MICROGRAMS_PER_CUBIC_METER,
    },
    "eco2": {
        "deviceClass": SensorDeviceClass.CO2,
        "friendlyName": "Co2",
        "unit": CONCENTRATION_PARTS_PER_MILLION,
    },
    "pm10": {
        "deviceClass": SensorDeviceClass.PM10,
        "friendlyName": "PM10",
        "unit": CONCENTRATION_MICROGRAMS_PER_CUBIC_METER,
    },
    "pm25": {
        "deviceClass": SensorDeviceClass.PM25,
        "friendlyName": "PM2.5",
        "unit": CONCENTRATION_MICROGRAMS_PER_CUBIC_METER,
    },
    "pm1": {
        "deviceClass": SensorDeviceClass.PM1,
        "friendlyName": "PM1",
        "unit": CONCENTRATION_MICROGRAMS_PER_CUBIC_METER,
    },
    "internal_temperature": {
        "deviceClass": SensorDeviceClass.TEMPERATURE,
        "friendlyName": "Temperature",
        "unit": UnitOfTemperature.CELSIUS,
    },
    "relative_humidity": {
        "deviceClass": SensorDeviceClass.HUMIDITY,
        "friendlyName": "Humidity",
        "unit": PERCENTAGE,
    },
    "pressure": {
        "deviceClass": SensorDeviceClass.PRESSURE,
        "friendlyName": "Pressure",
        "unit": UnitOfPressure.PA,
    },
    "aqi_value": {
        "deviceClass": SensorDeviceClass.AQI,
        "friendlyName": "Air Quality",
        "unit": None,
    },
}


@dataclass
class RadoffSensor:
    """Dataclass to store the entity data."""

    name: str
    value: Number
    device_class: SensorDeviceClass
    friendly_name: str
    unit: type[StrEnum] | str | None
    normalize_fn: Callable[[Number], float | int] | None


@dataclass
class Device:
    """API device."""

    device_id: str
    device_serial: str
    device_type: str
    name: str
    sensors: dict[str, RadoffSensor]
    connected: bool | None = None
    last_data_received: datetime | None = None


class API:
    """Radoff v2 API client."""

    BASE_DOMAIN = "https://v2.api.iot.radoff.life"
    PARENT_DOMAIN_PREFIX = "94e966f9"
    DEFAULT_TIMEOUT = (10, 30)

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
        self.domain_prefix: str = ""
        self.tokens: dict = {}
        self._token_expires_at: float = 0

        self.session = self._create_session()

    def _create_session(self) -> requests.Session:
        session = requests.Session()
        retry_strategy = Retry(
            total=3,
            backoff_factor=0.5,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["GET", "POST"],
        )
        adapter = HTTPAdapter(
            pool_connections=1, pool_maxsize=2, max_retries=retry_strategy
        )
        session.mount("https://", adapter)
        return session

    def _is_token_expired(self) -> bool:
        if not self.tokens:
            return True
        return time.time() >= (self._token_expires_at - 300)

    @property
    def controller_name(self) -> str:
        """Return the name of the controller."""
        return "cloud_poller_v2"

    def connect(self) -> bool:
        """Authenticate and resolve the user's domain prefix."""
        if not (self.username and self.password and self.client_id):
            raise APIAuthError("Missing authentication data.")

        _LOGGER.debug("Authenticating with AWS Cognito...")
        connection = AWSSRP(
            username=self.username,
            password=self.password,
            pool_id=self.pool_id,
            client_id=self.client_id,
            pool_region=self.pool_region,
        )
        auth_data = connection.authenticate_user()
        if not auth_data or "AuthenticationResult" not in auth_data:
            raise APIAuthError("Cognito returned no AuthenticationResult.")

        self.tokens = auth_data["AuthenticationResult"]
        expires_in = self.tokens.get("ExpiresIn", 3600)
        self._token_expires_at = time.time() + expires_in
        _LOGGER.info("Token will expire in %d seconds", expires_in)

        self.connected = True
        prefix = self._get_domain_prefix(self._get_bearer_token())
        if not prefix:
            raise DomainNotFoundError("No matching domain for this user.")
        self.domain_prefix = prefix
        _LOGGER.info("Successfully connected to Radoff v2 API, domain=%s", prefix)
        return True

    def disconnect(self) -> bool:
        """Drop the current session and tokens."""
        _LOGGER.debug("Disconnecting from API")
        self.connected = False
        self.tokens = {}
        self.domain_prefix = ""
        self._token_expires_at = 0
        if self.session:
            self.session.close()
            self.session = self._create_session()
        return True

    def get_devices(self) -> list[Device]:
        """Return the devices the user has access to."""
        if self._is_token_expired():
            _LOGGER.info("Token expired, reconnecting...")
            self.disconnect()
            self.connect()

        url = f"{self.BASE_DOMAIN}/data/devices"
        response = self.session.get(
            url,
            headers=self._get_headers(self._get_bearer_token()),
            timeout=self.DEFAULT_TIMEOUT,
        )
        self._check_response_status(response, url)

        devices_json = response.json().get("devices", [])
        _LOGGER.debug("Found %d devices in response", len(devices_json))

        device_list: list[Device] = []
        for device in devices_json:
            device_type = device.get("type")
            if device_type not in DEVICE_TYPES:
                _LOGGER.debug("Skipping unsupported device type %r", device_type)
                continue

            sensors = self._sensors_from_telemetry(device.get("telemetry") or {})
            connected = (
                device.get("connection_status") == "connected"
                if device.get("connection_status") is not None
                else None
            )
            last_data_received = _parse_timestamp(
                (device.get("telemetry") or {}).get("timestamp")
            )

            device_list.append(
                Device(
                    device_id=device.get("serial_number"),
                    device_serial=device.get("serial_number"),
                    device_type=device_type,
                    name=device.get("name") or device.get("serial_number"),
                    sensors=sensors,
                    connected=connected,
                    last_data_received=last_data_received,
                )
            )
        return device_list

    def _sensors_from_telemetry(self, telemetry: dict) -> dict[str, RadoffSensor]:
        sensors: dict[str, RadoffSensor] = {}
        for key, cfg in MAPPING.items():
            if key not in telemetry or telemetry[key] is None:
                continue
            sensors[key] = RadoffSensor(
                name=key,
                value=telemetry[key],
                device_class=cfg["deviceClass"],
                friendly_name=cfg["friendlyName"],
                unit=cfg["unit"],
                normalize_fn=cfg.get("normalize_fn"),
            )
        return sensors

    def _get_bearer_token(self) -> str:
        if self.tokens and "IdToken" in self.tokens:
            return self.tokens["IdToken"]
        raise BearerTokenNotFoundError("Error retrieving bearer token.")

    def _get_headers(self, bearer_token: str) -> dict[str, str]:
        return {
            "user-agent": "home-assistant-radoff-v2",
            "authorization": "Bearer " + bearer_token,
            "accept-encoding": "gzip",
            "content-type": "application/json",
            "accept": "application/json",
            "origin": "https://iot.radoff.life",
            "referer": "https://iot.radoff.life/",
        }

    def _get_domain_prefix(self, bearer_token: str) -> str | None:
        url = f"{self.BASE_DOMAIN}/data/user/me/domains"
        response = self.session.get(
            url, headers=self._get_headers(bearer_token), timeout=self.DEFAULT_TIMEOUT
        )
        if response.status_code != 200:
            _LOGGER.error(
                "Failed to get domains: status=%d, response=%s",
                response.status_code,
                response.text[:200],
            )
            return None
        data = response.json()
        for entry in data.get("domains", []):
            domain = entry.get("domain") or entry
            parent = domain.get("parent_domain_prefix")
            prefix = domain.get("prefix")
            if parent == self.PARENT_DOMAIN_PREFIX and prefix:
                return prefix
        # Fallback: first domain if the parent filter didn't match.
        for entry in data.get("domains", []):
            domain = entry.get("domain") or entry
            if domain.get("prefix"):
                return domain["prefix"]
        return None

    def _check_response_status(self, response: requests.Response, url: str = "") -> bool:
        if response.status_code == 200:
            return True
        _LOGGER.warning(
            "API request failed: status=%d, url=%s, response=%s",
            response.status_code,
            url or response.url,
            response.text[:200],
        )
        if response.status_code == 401:
            self.disconnect()
            raise APIAuthError("Authentication failed (HTTP 401). Token may be expired.")
        if response.status_code == 403:
            raise APIAuthError("Access forbidden (HTTP 403). Check account permissions.")
        if response.status_code == 429:
            raise APIAuthError(
                "API rate limit exceeded (HTTP 429). Increase polling interval above 60 s."
            )
        if response.status_code >= 500:
            raise APIAuthError(
                f"Radoff API server error (HTTP {response.status_code}). Will retry."
            )
        raise APIAuthError(
            f"API request failed with HTTP {response.status_code}: {response.text[:100]}"
        )


def _parse_timestamp(raw: str | None) -> datetime | None:
    """Parse an ISO-8601 timestamp into an aware datetime, tolerating missing TZ."""
    if not raw:
        return None
    parsed = dt_util.parse_datetime(raw)
    if parsed is None:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt_util.UTC)
    return parsed


class APIAuthError(Exception):
    """Exception class for auth error."""


class APIConnectionError(Exception):
    """Exception class for connection error."""


class DomainNotFoundError(Exception):
    """Exception class for domain not found error."""


class BearerTokenNotFoundError(Exception):
    """Exception class for bearer token not found/available."""
