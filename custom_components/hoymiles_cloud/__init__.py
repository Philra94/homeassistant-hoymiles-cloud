"""The Hoymiles Cloud Integration."""
from copy import deepcopy
import logging
from datetime import timedelta
import time
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

from .const import (
    AUTH_MODE_AUTO,
    BATTERY_MODE_IDS,
    CONF_APP_VERSION,
    CONF_AUTH_MODE,
    CONF_FETCH_ENERGY_FLOW,
    CONF_FETCH_EPS_PROFIT,
    CONF_FETCH_GRID_INDICATORS,
    DEFAULT_FETCH_ENERGY_FLOW,
    DEFAULT_FETCH_EPS_PROFIT,
    DEFAULT_FETCH_GRID_INDICATORS,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_STATIC_REFRESH_INTERVAL,
    DOMAIN,
    STORAGE_KEY,
    STORAGE_VERSION,
)
from .data import (
    add_schedule_entry,
    battery_settings_readable,
    build_schedule_editor_state,
    build_schedule_payload_from_draft,
    build_station_capabilities,
    get_schedule_draft,
    remove_schedule_entry,
    set_schedule_editor_selection,
    update_schedule_editor_draft,
)
from .hoymiles_api import HoymilesAPI
from .models import AIStatus, DeviceInventory, EPSProfit, EnergyFlow, FirmwareStatus, SettingRules, StationData

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [
    Platform.SENSOR,
    Platform.BINARY_SENSOR,
    Platform.NUMBER,
    Platform.SELECT,
    Platform.TEXT,
    Platform.BUTTON,
    Platform.SWITCH,
]

SERVICE_SET_BATTERY_MODE = "set_battery_mode"
SERVICE_SET_BATTERY_MODE_SETTINGS = "set_battery_mode_settings"
SERVICE_LOAD_SCHEDULE_DRAFT = "load_schedule_draft"
SERVICE_APPLY_SCHEDULE_DRAFT = "apply_schedule_draft"
SERVICE_RESET_SCHEDULE_DRAFT = "reset_schedule_draft"
SERVICE_ADD_SCHEDULE_ENTRY = "add_schedule_entry"
SERVICE_REMOVE_SCHEDULE_ENTRY = "remove_schedule_entry"
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
        if "schedule_editor" not in stored_data["stations"][station_id]:
            stored_data["stations"][station_id]["schedule_editor"] = {"modes": {}}
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


def _resolve_editor_mode(
    station_data: dict[str, Any],
    explicit_mode: int | None = None,
) -> int:
    """Return the active editor mode for a station."""
    if explicit_mode is not None:
        return explicit_mode

    editor_state = station_data.get("schedule_editor", {})
    selected_mode = editor_state.get("selected_mode")
    if isinstance(selected_mode, int):
        return selected_mode

    available_modes = editor_state.get("available_modes", [])
    if available_modes:
        return int(available_modes[0])

    raise HomeAssistantError("No editable schedule mode is available for this station")


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

    async def async_handle_load_schedule_draft(call: ServiceCall) -> None:
        station_id = str(call.data[SERVICE_FIELD_STATION_ID])
        config_entry_id = call.data.get(SERVICE_FIELD_CONFIG_ENTRY_ID)
        runtime = _resolve_runtime_for_station(hass, station_id, config_entry_id)
        station_data = runtime["coordinator"].data.get(station_id, {}) if runtime["coordinator"].data else {}
        mode = _resolve_editor_mode(
            station_data,
            int(call.data[SERVICE_FIELD_MODE]) if SERVICE_FIELD_MODE in call.data else None,
        )
        await runtime["load_schedule_draft"](station_id, mode)

    async def async_handle_apply_schedule_draft(call: ServiceCall) -> None:
        station_id = str(call.data[SERVICE_FIELD_STATION_ID])
        config_entry_id = call.data.get(SERVICE_FIELD_CONFIG_ENTRY_ID)
        runtime = _resolve_runtime_for_station(hass, station_id, config_entry_id)
        station_data = runtime["coordinator"].data.get(station_id, {}) if runtime["coordinator"].data else {}
        mode = _resolve_editor_mode(
            station_data,
            int(call.data[SERVICE_FIELD_MODE]) if SERVICE_FIELD_MODE in call.data else None,
        )
        await runtime["apply_schedule_draft"](station_id, mode)

    async def async_handle_reset_schedule_draft(call: ServiceCall) -> None:
        station_id = str(call.data[SERVICE_FIELD_STATION_ID])
        config_entry_id = call.data.get(SERVICE_FIELD_CONFIG_ENTRY_ID)
        runtime = _resolve_runtime_for_station(hass, station_id, config_entry_id)
        station_data = runtime["coordinator"].data.get(station_id, {}) if runtime["coordinator"].data else {}
        mode = _resolve_editor_mode(
            station_data,
            int(call.data[SERVICE_FIELD_MODE]) if SERVICE_FIELD_MODE in call.data else None,
        )
        await runtime["reset_schedule_draft"](station_id, mode)

    async def async_handle_add_schedule_entry(call: ServiceCall) -> None:
        station_id = str(call.data[SERVICE_FIELD_STATION_ID])
        config_entry_id = call.data.get(SERVICE_FIELD_CONFIG_ENTRY_ID)
        runtime = _resolve_runtime_for_station(hass, station_id, config_entry_id)
        station_data = runtime["coordinator"].data.get(station_id, {}) if runtime["coordinator"].data else {}
        mode = _resolve_editor_mode(
            station_data,
            int(call.data[SERVICE_FIELD_MODE]) if SERVICE_FIELD_MODE in call.data else None,
        )
        await runtime["add_schedule_entry"](station_id, mode)

    async def async_handle_remove_schedule_entry(call: ServiceCall) -> None:
        station_id = str(call.data[SERVICE_FIELD_STATION_ID])
        config_entry_id = call.data.get(SERVICE_FIELD_CONFIG_ENTRY_ID)
        runtime = _resolve_runtime_for_station(hass, station_id, config_entry_id)
        station_data = runtime["coordinator"].data.get(station_id, {}) if runtime["coordinator"].data else {}
        mode = _resolve_editor_mode(
            station_data,
            int(call.data[SERVICE_FIELD_MODE]) if SERVICE_FIELD_MODE in call.data else None,
        )
        await runtime["remove_schedule_entry"](station_id, mode)

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
    schedule_service_schema = vol.Schema(
        {
            vol.Required(SERVICE_FIELD_STATION_ID): vol.Any(cv.string, vol.Coerce(int)),
            vol.Optional(SERVICE_FIELD_MODE): vol.Coerce(int),
            vol.Optional(SERVICE_FIELD_CONFIG_ENTRY_ID): cv.string,
        }
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_LOAD_SCHEDULE_DRAFT,
        async_handle_load_schedule_draft,
        schema=schedule_service_schema,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_APPLY_SCHEDULE_DRAFT,
        async_handle_apply_schedule_draft,
        schema=schedule_service_schema,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_RESET_SCHEDULE_DRAFT,
        async_handle_reset_schedule_draft,
        schema=schedule_service_schema,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_ADD_SCHEDULE_ENTRY,
        async_handle_add_schedule_entry,
        schema=schedule_service_schema,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_REMOVE_SCHEDULE_ENTRY,
        async_handle_remove_schedule_entry,
        schema=schedule_service_schema,
    )
    domain_data["services_registered"] = True


async def _async_unregister_services(hass: HomeAssistant) -> None:
    """Remove domain services when the last entry unloads."""
    if _iter_runtimes(hass):
        return
    hass.services.async_remove(DOMAIN, SERVICE_SET_BATTERY_MODE)
    hass.services.async_remove(DOMAIN, SERVICE_SET_BATTERY_MODE_SETTINGS)
    hass.services.async_remove(DOMAIN, SERVICE_LOAD_SCHEDULE_DRAFT)
    hass.services.async_remove(DOMAIN, SERVICE_APPLY_SCHEDULE_DRAFT)
    hass.services.async_remove(DOMAIN, SERVICE_RESET_SCHEDULE_DRAFT)
    hass.services.async_remove(DOMAIN, SERVICE_ADD_SCHEDULE_ENTRY)
    hass.services.async_remove(DOMAIN, SERVICE_REMOVE_SCHEDULE_ENTRY)
    hass.data.get(DOMAIN, {}).pop("services_registered", None)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Hoymiles Cloud from a config entry."""
    username = entry.data[CONF_USERNAME]
    password = entry.data[CONF_PASSWORD]
    scan_interval = entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
    auth_mode = entry.data.get(CONF_AUTH_MODE, AUTH_MODE_AUTO)
    app_version = entry.data.get(CONF_APP_VERSION)
    fetch_grid_indicators = entry.options.get(
        CONF_FETCH_GRID_INDICATORS,
        DEFAULT_FETCH_GRID_INDICATORS,
    )
    fetch_energy_flow = entry.options.get(
        CONF_FETCH_ENERGY_FLOW,
        DEFAULT_FETCH_ENERGY_FLOW,
    )
    fetch_eps_profit = entry.options.get(
        CONF_FETCH_EPS_PROFIT,
        DEFAULT_FETCH_EPS_PROFIT,
    )

    session = async_get_clientsession(hass)
    api = HoymilesAPI(session, username, password)
    api.configure_auth(auth_mode=auth_mode, app_version=app_version)
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

    static_station_cache: dict[str, dict[str, Any]] = {}
    static_station_cache_at: dict[str, float] = {}

    async def _async_fetch_static_station_payload(station_id: str) -> dict[str, Any]:
        """Fetch slower-changing station metadata and device inventory."""
        try:
            station_info = await api.get_station_details(station_id)
        except Exception as err:
            _LOGGER.warning("Failed to get station details for station %s: %s", station_id, err)
            station_info = {}
        if station_info.get("name"):
            stations[station_id] = str(station_info["name"])

        try:
            setting_rules = await api.get_setting_rules(station_id)
        except Exception as err:
            _LOGGER.warning("Failed to get setting rules for station %s: %s", station_id, err)
            setting_rules = {}

        try:
            dtus = await api.get_dtus(station_id)
        except Exception as err:
            _LOGGER.warning("Failed to get DTUs for station %s: %s", station_id, err)
            dtus = []

        try:
            inverters = await api.get_inverters(station_id)
        except Exception as err:
            _LOGGER.warning("Failed to get inverters for station %s: %s", station_id, err)
            inverters = []

        try:
            batteries = await api.get_batteries(station_id)
        except Exception as err:
            _LOGGER.warning("Failed to get batteries for station %s: %s", station_id, err)
            batteries = []

        try:
            meters = await api.get_meters(station_id)
        except Exception as err:
            _LOGGER.warning("Failed to get meters for station %s: %s", station_id, err)
            meters = []

        try:
            microinverters = await api.get_microinverters_by_stations(station_id)
        except Exception as err:
            _LOGGER.warning("Failed to get microinverter details for station %s: %s", station_id, err)
            microinverters = {}

        try:
            eps_settings = await api.get_eps_settings(station_id)
        except Exception as err:
            _LOGGER.warning("Failed to get EPS settings for station %s: %s", station_id, err)
            eps_settings = {}

        try:
            ai_status = await api.get_ai_status(station_id)
        except Exception as err:
            _LOGGER.warning("Failed to get AI status for station %s: %s", station_id, err)
            ai_status = {}

        try:
            firmware = await api.get_firmware_status(station_id)
        except Exception as err:
            _LOGGER.warning("Failed to get firmware status for station %s: %s", station_id, err)
            firmware = {}

        return {
            "station_info": station_info,
            "setting_rules": SettingRules(setting_rules).as_dict(),
            "devices": DeviceInventory(
                dtus=dtus,
                inverters=inverters,
                batteries=batteries,
                meters=meters,
                microinverters=microinverters,
            ).as_dict(),
            "eps_settings": eps_settings,
            "ai_status": AIStatus(ai_status).as_dict(),
            "firmware": FirmwareStatus(firmware).as_dict(),
        }

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
                    now = time.monotonic()
                    if (
                        station_id not in static_station_cache
                        or now - static_station_cache_at.get(station_id, 0) >= DEFAULT_STATIC_REFRESH_INTERVAL
                    ):
                        static_station_cache[station_id] = await _async_fetch_static_station_payload(station_id)
                        static_station_cache_at[station_id] = now
                    static_payload = static_station_cache.get(station_id, {})

                    real_time_data = await api.get_real_time_data(station_id)

                    try:
                        pv_indicators = await api.get_pv_indicators(station_id)
                    except Exception as err:
                        _LOGGER.warning(
                            "Failed to get PV indicators for station %s: %s",
                            station_id,
                            err,
                        )
                        pv_indicators = {}

                    if fetch_grid_indicators:
                        try:
                            grid_indicators = await api.get_grid_indicators(station_id)
                        except Exception as err:
                            _LOGGER.warning(
                                "Failed to get grid indicators for station %s: %s",
                                station_id,
                                err,
                            )
                            grid_indicators = {}
                    else:
                        grid_indicators = {}

                    try:
                        load_indicators = await api.get_load_indicators(station_id)
                    except Exception as err:
                        _LOGGER.warning(
                            "Failed to get load indicators for station %s: %s",
                            station_id,
                            err,
                        )
                        load_indicators = {}

                    try:
                        battery_settings = await api.get_battery_settings(station_id)
                    except Exception as err:
                        _LOGGER.warning(
                            "Failed to get battery settings for station %s: %s",
                            station_id,
                            err,
                        )
                        battery_settings = {}

                    try:
                        relay_settings = await api.get_relay_settings(station_id)
                    except Exception as err:
                        _LOGGER.warning(
                            "Failed to get relay settings for station %s: %s",
                            station_id,
                            err,
                        )
                        relay_settings = {}

                    if fetch_energy_flow:
                        try:
                            energy_flow = await api.get_energy_flow(station_id)
                        except Exception as err:
                            _LOGGER.warning(
                                "Failed to get energy flow for station %s: %s",
                                station_id,
                                err,
                            )
                            energy_flow = {}
                    else:
                        energy_flow = {}

                    if fetch_eps_profit:
                        try:
                            eps_profit = await api.get_eps_profit(station_id)
                        except Exception as err:
                            _LOGGER.warning(
                                "Failed to get EPS profit for station %s: %s",
                                station_id,
                                err,
                            )
                            eps_profit = {}
                    else:
                        eps_profit = {}

                    station_stored_data = stored_data["stations"].setdefault(station_id, {})
                    enhanced_battery_settings, station_changed = _enhance_battery_settings(
                        battery_settings,
                        station_stored_data,
                    )
                    should_save_store = should_save_store or station_changed

                    refreshed[station_id] = StationData(
                        station_info=static_payload.get("station_info", {}),
                        real_time_data=real_time_data,
                        energy_flow=EnergyFlow(energy_flow).as_dict(),
                        pv_indicators=pv_indicators,
                        grid_indicators=grid_indicators,
                        load_indicators=load_indicators,
                        battery_settings=enhanced_battery_settings,
                        relay_settings=relay_settings,
                        eps_settings=static_payload.get("eps_settings", {}),
                        eps_profit=EPSProfit(eps_profit).as_dict(),
                        ai_status=static_payload.get("ai_status", {}),
                        setting_rules=static_payload.get("setting_rules", {}),
                        devices=static_payload.get("devices", {}),
                        firmware=static_payload.get("firmware", {}),
                        schedule_editor=build_schedule_editor_state(
                            enhanced_battery_settings,
                            station_stored_data,
                        ),
                        capabilities=build_station_capabilities(
                            real_time_data=real_time_data,
                            pv_indicators=pv_indicators,
                            battery_settings=enhanced_battery_settings,
                            microinverters_data=static_payload.get("devices", {}).get("microinverters", {}),
                            grid_indicators=grid_indicators,
                            load_indicators=load_indicators,
                            energy_flow=energy_flow,
                            relay_settings=relay_settings,
                            setting_rules=static_payload.get("setting_rules", {}),
                            devices=static_payload.get("devices", {}),
                            eps_settings=static_payload.get("eps_settings", {}),
                            eps_profit=eps_profit,
                            ai_status=static_payload.get("ai_status", {}),
                            firmware=static_payload.get("firmware", {}),
                            station_info=static_payload.get("station_info", {}),
                        ),
                    ).as_dict()

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
        "static_station_cache": static_station_cache,
        "fetch_grid_indicators": fetch_grid_indicators,
        "fetch_energy_flow": fetch_energy_flow,
        "fetch_eps_profit": fetch_eps_profit,
    }

    def async_refresh_local_editor_state(station_id: str | None = None) -> None:
        """Rebuild derived schedule editor state from current live data and storage."""
        if not coordinator.data:
            return
        updated_data = dict(coordinator.data)
        station_ids = [station_id] if station_id else list(updated_data)
        for current_station_id in station_ids:
            if current_station_id not in updated_data:
                continue
            station_payload = dict(updated_data[current_station_id])
            station_store = stored_data["stations"].setdefault(current_station_id, {})
            station_payload["schedule_editor"] = build_schedule_editor_state(
                station_payload.get("battery_settings", {}),
                station_store,
            )
            updated_data[current_station_id] = station_payload
        coordinator.async_set_updated_data(updated_data)

    def _get_schedule_editor_store_for_mode(station_id: str, mode: int) -> dict[str, Any]:
        """Return persisted editor storage seeded with the current live draft."""
        station_store = deepcopy(
            stored_data["stations"].setdefault(station_id, {}).get("schedule_editor", {"modes": {}})
        )
        station_store.setdefault("modes", {})
        if str(mode) not in station_store["modes"] and coordinator.data:
            mode_state = coordinator.data.get(station_id, {}).get("schedule_editor", {}).get("modes", {}).get(mode)
            if mode_state:
                station_store["modes"][str(mode)] = deepcopy(mode_state.get("draft", {}))
        return station_store

    async def async_save_schedule_editor_store(station_id: str, schedule_editor_store: dict[str, Any]) -> None:
        """Persist updated schedule editor storage and refresh derived local state."""
        stored_data["stations"].setdefault(station_id, {})
        stored_data["stations"][station_id]["schedule_editor"] = schedule_editor_store
        await store.async_save(stored_data)
        async_refresh_local_editor_state(station_id)

    async def async_update_soc(station_id: str, mode_name: str, value: int) -> None:
        """Persist the last known reserve SOC value for a station/mode."""
        stored_data["stations"].setdefault(station_id, {})
        stored_data["stations"][station_id][f"{mode_name}_soc"] = value
        await store.async_save(stored_data)

    async def async_set_schedule_editor_selection(
        station_id: str,
        *,
        selected_mode: int | None = None,
        mode: int | None = None,
        key: str | None = None,
        value: int | None = None,
    ) -> None:
        """Persist updated selection state for the schedule editor."""
        station_store = stored_data["stations"].setdefault(station_id, {}).get("schedule_editor", {})
        updated_store = set_schedule_editor_selection(
            station_store,
            selected_mode=selected_mode,
            mode=mode,
            key=key,
            value=value,
        )
        await async_save_schedule_editor_store(station_id, updated_store)

    async def async_set_schedule_editor_field(
        station_id: str,
        mode: int,
        field_path: tuple[Any, ...],
        value: Any,
    ) -> None:
        """Persist one draft field update."""
        station_store = _get_schedule_editor_store_for_mode(station_id, mode)
        updated_store = update_schedule_editor_draft(station_store, mode, field_path, value)
        await async_save_schedule_editor_store(station_id, updated_store)

    async def async_load_schedule_draft(station_id: str, mode: int) -> None:
        """Replace the stored draft with the current live payload for one mode."""
        station_store = stored_data["stations"].setdefault(station_id, {}).get("schedule_editor", {})
        updated_store = set_schedule_editor_selection(station_store, selected_mode=mode)
        updated_store.setdefault("modes", {}).pop(str(mode), None)
        await async_save_schedule_editor_store(station_id, updated_store)

    async def async_reset_schedule_draft(station_id: str, mode: int) -> None:
        """Discard local edits and return to the live schedule."""
        await async_load_schedule_draft(station_id, mode)

    async def async_apply_schedule_draft(station_id: str, mode: int) -> None:
        """Validate and write the current draft back to Hoymiles."""
        station_data = coordinator.data.get(station_id, {}) if coordinator.data else {}
        editor_state = station_data.get("schedule_editor", {})
        mode_state = editor_state.get("modes", {}).get(mode)
        if not mode_state:
            raise HomeAssistantError("No draft state is available for this schedule mode")
        if mode_state["validation_errors"]:
            raise HomeAssistantError(mode_state["validation_errors"][0])

        payload = build_schedule_payload_from_draft(mode, mode_state["draft"])
        if not await api.set_battery_mode_settings(station_id, mode, payload, merge=True):
            raise HomeAssistantError("Failed to apply the Hoymiles schedule draft")

        await async_load_schedule_draft(station_id, mode)
        await coordinator.async_request_refresh()

    async def async_add_schedule_entry_for_mode(station_id: str, mode: int) -> None:
        """Add a new schedule row or date window for the selected editor mode."""
        station_store = _get_schedule_editor_store_for_mode(station_id, mode)
        updated_store = add_schedule_entry(station_store, mode)
        updated_store = set_schedule_editor_selection(updated_store, selected_mode=mode)
        await async_save_schedule_editor_store(station_id, updated_store)

    async def async_remove_schedule_entry_for_mode(station_id: str, mode: int) -> None:
        """Remove the selected schedule row or date window for the selected editor mode."""
        station_store = _get_schedule_editor_store_for_mode(station_id, mode)
        updated_store = remove_schedule_entry(station_store, mode)
        updated_store = set_schedule_editor_selection(updated_store, selected_mode=mode)
        await async_save_schedule_editor_store(station_id, updated_store)

    hass.data[DOMAIN][entry.entry_id]["update_soc"] = async_update_soc
    hass.data[DOMAIN][entry.entry_id]["set_schedule_editor_selection"] = async_set_schedule_editor_selection
    hass.data[DOMAIN][entry.entry_id]["set_schedule_editor_field"] = async_set_schedule_editor_field
    hass.data[DOMAIN][entry.entry_id]["load_schedule_draft"] = async_load_schedule_draft
    hass.data[DOMAIN][entry.entry_id]["apply_schedule_draft"] = async_apply_schedule_draft
    hass.data[DOMAIN][entry.entry_id]["reset_schedule_draft"] = async_reset_schedule_draft
    hass.data[DOMAIN][entry.entry_id]["add_schedule_entry"] = async_add_schedule_entry_for_mode
    hass.data[DOMAIN][entry.entry_id]["remove_schedule_entry"] = async_remove_schedule_entry_for_mode

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