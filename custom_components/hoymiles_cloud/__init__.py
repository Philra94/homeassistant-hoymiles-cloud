"""The Hoymiles Cloud Integration."""
import logging
from datetime import timedelta
from typing import Any

import async_timeout
from homeassistant.config_entries import ConfigEntry, ConfigEntryAuthFailed
from homeassistant.const import CONF_PASSWORD, CONF_SCAN_INTERVAL, CONF_USERNAME, Platform
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import ConfigEntryNotReady, HomeAssistantError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
import voluptuous as vol

from .const import BATTERY_MODE_IDS, DEFAULT_SCAN_INTERVAL, DOMAIN, STORAGE_KEY, STORAGE_VERSION
from .data import battery_settings_readable, build_station_capabilities
from .hoymiles_api import HoymilesAPI

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [Platform.SENSOR, Platform.NUMBER, Platform.SELECT]

SERVICE_SET_BATTERY_MODE = "set_battery_mode"
SERVICE_SET_BATTERY_MODE_SETTINGS = "set_battery_mode_settings"
SERVICE_FIELD_STATION_ID = "station_id"
SERVICE_FIELD_MODE = "mode"
SERVICE_FIELD_SETTINGS = "settings"
SERVICE_FIELD_MERGE = "merge"
SERVICE_FIELD_CONFIG_ENTRY_ID = "config_entry_id"


def _get_mode_storage_key(mode_num: int) -> str:
    """Convert a battery mode number to the persistent storage key."""
    mode_keys = {
        1: "self_consumption",
        2: "economy_mode",
        3: "backup",
        4: "off_grid_mode",
        7: "peak_shaving_mode",
        8: "time_of_use_mode",
    }
    return mode_keys.get(mode_num, f"mode_{mode_num}")


def _ensure_station_storage(stored_data: dict, stations: dict[str, str]) -> bool:
    """Ensure per-station storage exists."""
    changed = False
    stored_data.setdefault("stations", {})
    for station_id in stations:
        if station_id not in stored_data["stations"]:
            stored_data["stations"][station_id] = {}
            changed = True
    return changed


def _enhance_battery_settings(
    battery_settings: dict,
    station_stored_data: dict,
) -> tuple[dict, bool]:
    """Merge readable battery settings with persisted SOC values."""
    enhanced = dict(battery_settings)
    stored_soc: dict[str, int] = {}
    should_save = False

    if not battery_settings_readable(battery_settings):
        return enhanced, False

    mode_data = battery_settings.get("mode_data", {})
    for k_key, mode_settings in mode_data.items():
        if not k_key.startswith("k_") or "reserve_soc" not in mode_settings:
            continue

        try:
            mode_num = int(k_key.split("_", 1)[1])
        except ValueError:
            continue

        storage_key = _get_mode_storage_key(mode_num)
        reserve_soc = mode_settings["reserve_soc"]
        stored_soc[storage_key] = reserve_soc

        if station_stored_data.get(f"{storage_key}_soc") != reserve_soc:
            station_stored_data[f"{storage_key}_soc"] = reserve_soc
            should_save = True

    enhanced["stored_soc"] = stored_soc
    return enhanced, should_save


def _iter_runtimes(hass: HomeAssistant) -> list[dict[str, Any]]:
    """Return all configured runtime payloads for this domain."""
    runtimes: list[dict[str, Any]] = []
    for value in hass.data.get(DOMAIN, {}).values():
        if isinstance(value, dict) and "api" in value and "stations" in value:
            runtimes.append(value)
    return runtimes


def _resolve_runtime_for_station(
    hass: HomeAssistant,
    station_id: str,
    config_entry_id: str | None = None,
) -> dict[str, Any]:
    """Return the runtime data for a station."""
    matching_runtimes = []
    for runtime in _iter_runtimes(hass):
        entry = runtime.get("entry")
        if config_entry_id and entry and entry.entry_id != config_entry_id:
            continue
        if station_id in runtime.get("stations", {}):
            matching_runtimes.append(runtime)

    if not matching_runtimes:
        raise HomeAssistantError(f"Unknown Hoymiles station_id: {station_id}")
    if len(matching_runtimes) > 1 and not config_entry_id:
        raise HomeAssistantError(
            "Station id is ambiguous across multiple Hoymiles config entries; "
            "include config_entry_id in the service call"
        )
    return matching_runtimes[0]


async def _async_register_services(hass: HomeAssistant) -> None:
    """Register domain services once."""
    domain_data = hass.data.setdefault(DOMAIN, {})
    if domain_data.get("services_registered"):
        return

    async def async_handle_set_battery_mode(call: ServiceCall) -> None:
        station_id = str(call.data[SERVICE_FIELD_STATION_ID])
        mode = int(call.data[SERVICE_FIELD_MODE])
        config_entry_id = call.data.get(SERVICE_FIELD_CONFIG_ENTRY_ID)
        runtime = _resolve_runtime_for_station(hass, station_id, config_entry_id)

        if mode not in BATTERY_MODE_IDS:
            raise HomeAssistantError(f"Unsupported Hoymiles battery mode: {mode}")

        if not await runtime["api"].set_battery_mode(station_id, mode):
            raise HomeAssistantError("Failed to update the Hoymiles battery mode")

        await runtime["coordinator"].async_request_refresh()

    async def async_handle_set_battery_mode_settings(call: ServiceCall) -> None:
        station_id = str(call.data[SERVICE_FIELD_STATION_ID])
        mode = int(call.data[SERVICE_FIELD_MODE])
        settings = dict(call.data[SERVICE_FIELD_SETTINGS])
        merge = bool(call.data.get(SERVICE_FIELD_MERGE, True))
        config_entry_id = call.data.get(SERVICE_FIELD_CONFIG_ENTRY_ID)
        runtime = _resolve_runtime_for_station(hass, station_id, config_entry_id)

        if mode not in BATTERY_MODE_IDS:
            raise HomeAssistantError(f"Unsupported Hoymiles battery mode: {mode}")

        if not await runtime["api"].set_battery_mode_settings(
            station_id,
            mode,
            settings,
            merge=merge,
        ):
            raise HomeAssistantError("Failed to update the Hoymiles battery mode settings")

        reserve_soc = settings.get("reserve_soc")
        if reserve_soc is not None:
            await runtime["update_soc"](
                station_id,
                _get_mode_storage_key(mode),
                int(reserve_soc),
            )

        await runtime["coordinator"].async_request_refresh()

    hass.services.async_register(
        DOMAIN,
        SERVICE_SET_BATTERY_MODE,
        async_handle_set_battery_mode,
        schema=vol.Schema(
            {
                vol.Required(SERVICE_FIELD_STATION_ID): vol.Any(cv.string, vol.Coerce(int)),
                vol.Required(SERVICE_FIELD_MODE): vol.Coerce(int),
                vol.Optional(SERVICE_FIELD_CONFIG_ENTRY_ID): cv.string,
            }
        ),
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_SET_BATTERY_MODE_SETTINGS,
        async_handle_set_battery_mode_settings,
        schema=vol.Schema(
            {
                vol.Required(SERVICE_FIELD_STATION_ID): vol.Any(cv.string, vol.Coerce(int)),
                vol.Required(SERVICE_FIELD_MODE): vol.Coerce(int),
                vol.Required(SERVICE_FIELD_SETTINGS): dict,
                vol.Optional(SERVICE_FIELD_MERGE, default=True): cv.boolean,
                vol.Optional(SERVICE_FIELD_CONFIG_ENTRY_ID): cv.string,
            }
        ),
    )
    domain_data["services_registered"] = True


async def _async_unregister_services(hass: HomeAssistant) -> None:
    """Remove domain services when the last entry unloads."""
    if _iter_runtimes(hass):
        return
    hass.services.async_remove(DOMAIN, SERVICE_SET_BATTERY_MODE)
    hass.services.async_remove(DOMAIN, SERVICE_SET_BATTERY_MODE_SETTINGS)
    hass.data.get(DOMAIN, {}).pop("services_registered", None)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Hoymiles Cloud from a config entry."""
    username = entry.data[CONF_USERNAME]
    password = entry.data[CONF_PASSWORD]
    scan_interval = entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)

    session = async_get_clientsession(hass)
    api = HoymilesAPI(session, username, password)
    store = Store(hass, STORAGE_VERSION, STORAGE_KEY)
    stored_data = await store.async_load() or {}

    try:
        auth_result = await api.authenticate()
    except Exception as err:
        raise ConfigEntryNotReady(f"Unable to authenticate with Hoymiles Cloud: {err}") from err

    if not auth_result:
        raise ConfigEntryAuthFailed(
            "Hoymiles authentication failed: "
            f"{api.last_auth_status} - {api.last_auth_message} "
            f"({api.last_auth_attempt_summary})"
        )

    try:
        stations = await api.get_stations()
    except Exception as err:
        raise ConfigEntryNotReady(f"Unable to fetch Hoymiles stations: {err}") from err

    if not stations:
        raise ConfigEntryNotReady("No Hoymiles stations were returned for this account")

    if _ensure_station_storage(stored_data, stations):
        await store.async_save(stored_data)

    async def async_update_data():
        """Fetch data from API."""
        try:
            async with async_timeout.timeout(30):
                if api.is_token_expired() and not await api.authenticate():
                    raise ConfigEntryAuthFailed(
                        "Hoymiles authentication failed: "
                        f"{api.last_auth_status} - {api.last_auth_message} "
                        f"({api.last_auth_attempt_summary})"
                    )

                refreshed: dict[str, dict] = {}
                should_save_store = False

                for station_id in stations:
                    real_time_data = await api.get_real_time_data(station_id)

                    try:
                        microinverters_data = await api.get_microinverters_by_stations(station_id)
                    except Exception as err:
                        _LOGGER.warning(
                            "Failed to get microinverter details for station %s: %s",
                            station_id,
                            err,
                        )
                        microinverters_data = {}

                    try:
                        pv_indicators = await api.get_pv_indicators(station_id)
                    except Exception as err:
                        _LOGGER.warning(
                            "Failed to get PV indicators for station %s: %s",
                            station_id,
                            err,
                        )
                        pv_indicators = {}

                    try:
                        battery_settings = await api.get_battery_settings(station_id)
                    except Exception as err:
                        _LOGGER.warning(
                            "Failed to get battery settings for station %s: %s",
                            station_id,
                            err,
                        )
                        battery_settings = {}

                    station_stored_data = stored_data["stations"].setdefault(station_id, {})
                    enhanced_battery_settings, station_changed = _enhance_battery_settings(
                        battery_settings,
                        station_stored_data,
                    )
                    should_save_store = should_save_store or station_changed

                    refreshed[station_id] = {
                        "real_time_data": real_time_data,
                        "microinverters_data": microinverters_data,
                        "pv_indicators": pv_indicators,
                        "battery_settings": enhanced_battery_settings,
                        "capabilities": build_station_capabilities(
                            real_time_data=real_time_data,
                            pv_indicators=pv_indicators,
                            battery_settings=enhanced_battery_settings,
                            microinverters_data=microinverters_data,
                        ),
                    }

                if should_save_store:
                    await store.async_save(stored_data)

                return refreshed
        except ConfigEntryAuthFailed:
            raise
        except Exception as err:
            raise UpdateFailed(f"Error updating data: {err}") from err

    coordinator = DataUpdateCoordinator(
        hass,
        _LOGGER,
        name=DOMAIN,
        update_method=async_update_data,
        update_interval=timedelta(seconds=scan_interval),
    )

    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = {
        "api": api,
        "coordinator": coordinator,
        "stations": stations,
        "store": store,
        "stored_data": stored_data,
        "entry": entry,
    }

    async def async_update_soc(station_id: str, mode_name: str, value: int) -> None:
        """Persist the last known reserve SOC value for a station/mode."""
        stored_data["stations"].setdefault(station_id, {})
        stored_data["stations"][station_id][f"{mode_name}_soc"] = value
        await store.async_save(stored_data)

    hass.data[DOMAIN][entry.entry_id]["update_soc"] = async_update_soc

    await _async_register_services(hass)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(update_listener))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id, None)
        await _async_unregister_services(hass)
    return unload_ok


async def update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Handle options update."""
    await hass.config_entries.async_reload(entry.entry_id) 