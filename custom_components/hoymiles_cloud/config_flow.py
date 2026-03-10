"""Config flow for Hoymiles Cloud integration."""
import logging
from typing import Any, Dict, Optional

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.const import (
    CONF_PASSWORD,
    CONF_USERNAME,
    CONF_SCAN_INTERVAL,
)
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .auth import AUTH_ERROR_NO_ACCESSIBLE_STATIONS, auth_error_to_config_error
from .const import AUTH_MODE_AUTO, AUTH_MODE_OPTIONS, CONF_APP_VERSION, CONF_AUTH_MODE, DEFAULT_SCAN_INTERVAL, DOMAIN
from .hoymiles_api import HoymilesAPI

_LOGGER = logging.getLogger(__name__)

def _normalize_app_version(value: Any) -> str | None:
    """Normalize an optional app-version override."""
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _build_user_schema(
    default_auth_mode: str = AUTH_MODE_AUTO,
    default_app_version: str | None = None,
) -> vol.Schema:
    """Build the initial config-flow schema."""
    return vol.Schema(
        {
            vol.Required(CONF_USERNAME): str,
            vol.Required(CONF_PASSWORD): str,
            vol.Required(CONF_AUTH_MODE, default=default_auth_mode): vol.In(AUTH_MODE_OPTIONS),
            vol.Optional(CONF_APP_VERSION, default=default_app_version or ""): str,
        }
    )


STEP_USER_DATA_SCHEMA = _build_user_schema()


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Hoymiles Cloud."""

    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        """Get the options flow for this handler."""
        return OptionsFlowHandler(config_entry)

    async def async_step_user(
        self, user_input: Optional[Dict[str, Any]] = None
    ) -> FlowResult:
        """Handle the initial step."""
        errors: Dict[str, str] = {}

        if user_input is not None:
            username = user_input[CONF_USERNAME]
            password = user_input[CONF_PASSWORD]
            auth_mode = user_input.get(CONF_AUTH_MODE, AUTH_MODE_AUTO)
            app_version = _normalize_app_version(user_input.get(CONF_APP_VERSION))

            session = async_get_clientsession(self.hass)
            api = HoymilesAPI(session, username, password)
            api.configure_auth(auth_mode=auth_mode, app_version=app_version)

            try:
                # Test authentication
                authenticated = await api.authenticate()
                if not authenticated:
                    _LOGGER.error(
                        "Hoymiles authentication rejected via %s: %s - %s (%s)",
                        api.last_auth_attempt,
                        api.last_auth_status,
                        api.last_auth_message,
                        api.last_auth_attempt_summary,
                    )
                    errors["base"] = auth_error_to_config_error(api.last_auth_error_key)
                    return self.async_show_form(
                        step_id="user",
                        data_schema=_build_user_schema(
                            default_auth_mode=auth_mode,
                            default_app_version=app_version,
                        ),
                        errors=errors,
                    )

                user = await api.get_current_user()
                if not user:
                    _LOGGER.warning(
                        "Hoymiles auth succeeded for %s but user profile lookup returned empty data",
                        username,
                    )

                # Test getting stations
                stations = await api.get_stations()
                if not stations:
                    errors["base"] = AUTH_ERROR_NO_ACCESSIBLE_STATIONS
                    return self.async_show_form(
                        step_id="user",
                        data_schema=STEP_USER_DATA_SCHEMA,
                        errors=errors,
                    )

                # Check if already configured with this username
                await self.async_set_unique_id(username)
                self._abort_if_unique_id_configured()

                return self.async_create_entry(
                    title=username,
                    data={
                        CONF_USERNAME: username,
                        CONF_PASSWORD: password,
                    },
                    options={
                        CONF_SCAN_INTERVAL: DEFAULT_SCAN_INTERVAL,
                        CONF_AUTH_MODE: auth_mode,
                        CONF_APP_VERSION: app_version or "",
                    },
                )

            except Exception as e:
                _LOGGER.error("Error connecting to Hoymiles API: %s", e)
                errors["base"] = "cannot_connect"

        return self.async_show_form(
            step_id="user", data_schema=STEP_USER_DATA_SCHEMA, errors=errors
        )


class OptionsFlowHandler(config_entries.OptionsFlow):
    """Handle options flow for Hoymiles Cloud."""

    def __init__(self, config_entry):
        """Initialize options flow."""
        self.config_entry = config_entry

    async def async_step_init(self, user_input=None):
        """Manage the options."""
        if user_input is not None:
            user_input[CONF_APP_VERSION] = _normalize_app_version(user_input.get(CONF_APP_VERSION)) or ""
            return self.async_create_entry(title="", data=user_input)

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_SCAN_INTERVAL,
                        default=self.config_entry.options.get(
                            CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL
                        ),
                    ): vol.All(vol.Coerce(int), vol.Range(min=30, max=3600)),
                    vol.Required(
                        CONF_AUTH_MODE,
                        default=self.config_entry.options.get(CONF_AUTH_MODE, AUTH_MODE_AUTO),
                    ): vol.In(AUTH_MODE_OPTIONS),
                    vol.Optional(
                        CONF_APP_VERSION,
                        default=self.config_entry.options.get(CONF_APP_VERSION, ""),
                    ): str,
                }
            ),
        ) 