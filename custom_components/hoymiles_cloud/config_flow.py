"""Config flow for Hoymiles Cloud integration."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.const import CONF_PASSWORD, CONF_SCAN_INTERVAL, CONF_USERNAME
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .auth import AUTH_ERROR_NO_ACCESSIBLE_STATIONS, auth_error_to_config_error
from .const import (
    AUTH_MODE_AUTO,
    AUTH_MODE_OPTIONS,
    CONF_APP_VERSION,
    CONF_AUTH_MODE,
    CONF_FETCH_ENERGY_FLOW,
    CONF_FETCH_EPS_PROFIT,
    CONF_FETCH_GRID_INDICATORS,
    DEFAULT_FETCH_ENERGY_FLOW,
    DEFAULT_FETCH_EPS_PROFIT,
    DEFAULT_FETCH_GRID_INDICATORS,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
)
from .hoymiles_api import HoymilesAPI

_LOGGER = logging.getLogger(__name__)


def _build_user_schema(defaults: dict[str, Any] | None = None) -> vol.Schema:
    """Return the config-flow schema for user credentials."""
    defaults = defaults or {}
    return vol.Schema(
        {
            vol.Required(CONF_USERNAME, default=defaults.get(CONF_USERNAME, "")): str,
            vol.Required(CONF_PASSWORD, default=defaults.get(CONF_PASSWORD, "")): str,
            vol.Required(
                CONF_AUTH_MODE,
                default=defaults.get(CONF_AUTH_MODE, AUTH_MODE_AUTO),
            ): vol.In(AUTH_MODE_OPTIONS),
            vol.Optional(
                CONF_APP_VERSION,
                default=defaults.get(CONF_APP_VERSION, ""),
            ): str,
        }
    )


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Hoymiles Cloud."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize the Hoymiles config flow."""
        self._pending_entry_data: dict[str, Any] | None = None
        self._pending_station_names: list[str] = []
        self._pending_username: str | None = None

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        """Get the options flow for this handler."""
        return OptionsFlowHandler(config_entry)

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}
        schema = _build_user_schema(user_input)

        if user_input is None:
            return self.async_show_form(step_id="user", data_schema=schema, errors=errors)

        username = user_input[CONF_USERNAME]
        password = user_input[CONF_PASSWORD]
        auth_mode = user_input.get(CONF_AUTH_MODE, AUTH_MODE_AUTO)
        app_version = user_input.get(CONF_APP_VERSION, "").strip() or None

        session = async_get_clientsession(self.hass)
        api = HoymilesAPI(session, username, password)
        api.configure_auth(auth_mode=auth_mode, app_version=app_version)

        try:
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
                return self.async_show_form(step_id="user", data_schema=schema, errors=errors)

            stations = await api.get_stations()
            if not stations:
                errors["base"] = AUTH_ERROR_NO_ACCESSIBLE_STATIONS
                return self.async_show_form(step_id="user", data_schema=schema, errors=errors)

            station_metadata: dict[str, dict[str, Any]] = {}
            for station_id, station_name in stations.items():
                try:
                    details = await api.get_station_details(station_id)
                except Exception as err:
                    _LOGGER.debug("Failed to fetch station details during config flow: %s", err)
                    details = {}
                station_metadata[station_id] = {
                    "name": details.get("name") or station_name,
                    "timezone": details.get("timezone") or details.get("tz_name"),
                    "classify": details.get("classify"),
                }

            self._pending_entry_data = {
                CONF_USERNAME: username,
                CONF_PASSWORD: password,
                CONF_AUTH_MODE: auth_mode,
                "station_metadata": station_metadata,
            }
            if app_version:
                self._pending_entry_data[CONF_APP_VERSION] = app_version
            self._pending_station_names = [item["name"] for item in station_metadata.values()]
            self._pending_username = username
            return await self.async_step_confirm()

        except Exception as err:
            _LOGGER.error("Error connecting to Hoymiles API: %s", err)
            errors["base"] = "cannot_connect"
            return self.async_show_form(step_id="user", data_schema=schema, errors=errors)

    async def async_step_confirm(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Confirm the discovered stations before creating the entry."""
        if self._pending_entry_data is None or self._pending_username is None:
            return await self.async_step_user()

        if user_input is not None:
            await self.async_set_unique_id(self._pending_username)
            self._abort_if_unique_id_configured()
            return self.async_create_entry(
                title=self._pending_username,
                data=self._pending_entry_data,
                options={
                    CONF_SCAN_INTERVAL: DEFAULT_SCAN_INTERVAL,
                    CONF_FETCH_GRID_INDICATORS: DEFAULT_FETCH_GRID_INDICATORS,
                    CONF_FETCH_ENERGY_FLOW: DEFAULT_FETCH_ENERGY_FLOW,
                    CONF_FETCH_EPS_PROFIT: DEFAULT_FETCH_EPS_PROFIT,
                },
            )

        return self.async_show_form(
            step_id="confirm",
            data_schema=vol.Schema({}),
            description_placeholders={
                "stations": ", ".join(self._pending_station_names),
            },
        )

    async def async_step_reauth(self, entry_data: dict[str, Any]) -> FlowResult:
        """Prompt for replacement credentials for an existing account."""
        self._reauth_entry = self.hass.config_entries.async_get_entry(self.context["entry_id"])
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Validate the new credentials before updating the existing entry."""
        entry = self._reauth_entry
        if entry is None:
            return self.async_abort(reason="unknown")
        errors: dict[str, str] = {}
        defaults = {CONF_USERNAME: entry.data[CONF_USERNAME], CONF_PASSWORD: "",
                    CONF_AUTH_MODE: entry.data.get(CONF_AUTH_MODE, AUTH_MODE_AUTO),
                    CONF_APP_VERSION: entry.data.get(CONF_APP_VERSION, "")}
        if user_input is not None:
            username = user_input[CONF_USERNAME].strip()
            if username.casefold() != entry.data[CONF_USERNAME].casefold():
                errors["base"] = "account_mismatch"
                return self.async_show_form(
                    step_id="reauth_confirm",
                    data_schema=_build_user_schema(user_input),
                    errors=errors,
                )
            session = async_get_clientsession(self.hass)
            api = HoymilesAPI(session, username, user_input[CONF_PASSWORD])
            api.configure_auth(
                auth_mode=user_input.get(CONF_AUTH_MODE, AUTH_MODE_AUTO),
                app_version=user_input.get(CONF_APP_VERSION, "").strip() or None,
            )
            try:
                authenticated = await api.authenticate()
                if authenticated and not await api.get_stations():
                    errors["base"] = AUTH_ERROR_NO_ACCESSIBLE_STATIONS
                elif not authenticated:
                    errors["base"] = auth_error_to_config_error(api.last_auth_error_key)
            except Exception as err:
                _LOGGER.debug("Reauthentication failed: %s", err)
                errors["base"] = "cannot_connect"
            if not errors:
                for other in self.hass.config_entries.async_entries(DOMAIN):
                    if other.entry_id != entry.entry_id and (
                        other.unique_id or other.data.get(CONF_USERNAME, "")
                    ).casefold() == username.casefold():
                        errors["base"] = "already_configured"
                        break
            if not errors:
                data = dict(entry.data)
                data.update({CONF_USERNAME: username, CONF_PASSWORD: user_input[CONF_PASSWORD],
                             CONF_AUTH_MODE: user_input.get(CONF_AUTH_MODE, AUTH_MODE_AUTO)})
                app_version = user_input.get(CONF_APP_VERSION, "").strip()
                if app_version:
                    data[CONF_APP_VERSION] = app_version
                else:
                    data.pop(CONF_APP_VERSION, None)
                self.hass.config_entries.async_update_entry(entry, data=data)
                await self.hass.config_entries.async_reload(entry.entry_id)
                return self.async_abort(reason="reauth_successful")
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=_build_user_schema(user_input or defaults),
            errors=errors,
        )


class OptionsFlowHandler(config_entries.OptionsFlow):
    """Handle options flow for Hoymiles Cloud."""

    def __init__(self, config_entry) -> None:
        """Initialize options flow."""
        self._config_entry = config_entry

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Manage the options."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_SCAN_INTERVAL,
                        default=self.config_entry.options.get(
                            CONF_SCAN_INTERVAL,
                            DEFAULT_SCAN_INTERVAL,
                        ),
                    ): vol.All(vol.Coerce(int), vol.Range(min=30, max=3600)),
                    vol.Required(
                        CONF_FETCH_GRID_INDICATORS,
                        default=self.config_entry.options.get(
                            CONF_FETCH_GRID_INDICATORS,
                            DEFAULT_FETCH_GRID_INDICATORS,
                        ),
                    ): bool,
                    vol.Required(
                        CONF_FETCH_ENERGY_FLOW,
                        default=self.config_entry.options.get(
                            CONF_FETCH_ENERGY_FLOW,
                            DEFAULT_FETCH_ENERGY_FLOW,
                        ),
                    ): bool,
                    vol.Required(
                        CONF_FETCH_EPS_PROFIT,
                        default=self.config_entry.options.get(
                            CONF_FETCH_EPS_PROFIT,
                            DEFAULT_FETCH_EPS_PROFIT,
                        ),
                    ): bool,
                }
            ),
        )
