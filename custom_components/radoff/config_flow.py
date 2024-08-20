"""Config flow for radoff integration."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_CLIENT_ID, CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError

from .api import API
from .const import CONF_POOL_ID, CONF_POOL_REGION, DOMAIN

_LOGGER = logging.getLogger(__name__)


STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_USERNAME): str,
        vol.Required(CONF_PASSWORD): str,
        vol.Required(CONF_CLIENT_ID): str,
        vol.Required(CONF_POOL_ID): str,
        vol.Required(CONF_POOL_REGION): str,
    }
)


async def validate_input(hass: HomeAssistant, data: dict[str, Any]) -> dict[str, Any]:
    """Validate the user input allows us to connect."""

    api = API(
        username=data[CONF_USERNAME],
        password=data[CONF_PASSWORD],
        client_id=data[CONF_CLIENT_ID],
        pool_id=data[CONF_POOL_ID],
        pool_region=data[CONF_POOL_REGION],
    )

    if not await hass.async_add_executor_job(api.connect):
        raise InvalidAuth

    return {"title": "Radoff", "username": data[CONF_USERNAME]}


class ConfigPatternFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for radoff."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                info = await validate_input(self.hass, user_input)
            except CannotConnect:
                errors["base"] = "cannot_connect"
            except InvalidAuth:
                errors["base"] = "invalid_auth"
            except Exception:
                _LOGGER.exception("Unexpected exception")
                errors["base"] = "unknown"
            else:
                await self.async_set_unique_id(info.get("username"))
                self._abort_if_unique_id_configured()
                return self.async_create_entry(title=info["title"], data=user_input)

        return self.async_show_form(
            step_id="user", data_schema=STEP_USER_DATA_SCHEMA, errors=errors
        )


class CannotConnect(HomeAssistantError):
    """Error to indicate we cannot connect."""


class InvalidAuth(HomeAssistantError):
    """Error to indicate there is invalid auth."""
