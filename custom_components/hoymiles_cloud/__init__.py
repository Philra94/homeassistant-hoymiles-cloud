"""The Hoymiles Cloud Integration."""
from copy import deepcopy
import asyncio
import logging
from datetime import timedelta
import time
from typing import Any

from homeassistant.config_entries import ConfigEntry, ConfigEntryAuthFailed
from homeassistant.const import CONF_PASSWORD, CONF_SCAN_INTERVAL, CONF_USERNAME, Platform
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import ConfigEntryNotReady, HomeAssistantError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util
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
    MODULE_DATA_CACHE_INTERVAL,
    STORAGE_KEY,
    STORAGE_VERSION,
)
from .data import (
    add_schedule_entry,
    battery_settings_readable,
    build_schedule_editor_state,
    build_schedule_payload_from_draft,
    build_station_capabilities,
    find_placeholder_pv_channels,
    get_schedule_draft,
    merge_missing_pv_channel_values,
    remove_schedule_entry,
    seed_missing_pv_channels,
    set_schedule_editor_selection,
    update_schedule_editor_draft,
)
from .hoymiles_api import HoymilesAPI, LiveDataAuthError
from .models import AIStatus, DeviceInventory, EPSProfit, EnergyFlow, FirmwareStatus, SettingRules, StationData
from .storage import entry_storage_key, migrate_legacy_stations

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

        runtime["control_cache_at"].pop(station_id, None)
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

        runtime["control_cache_at"].pop(station_id, None)
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


# Reserve-SOC entities were originally keyed by a slugified mode name and are
# now keyed by the numeric mode id. Without a migration Home Assistant keeps the
# old entry registered and gives the new entity a "_2" suffix, leaving users
# with a dead duplicate and silently broken automations - see issue #43.
LEGACY_RESERVE_SOC_MODE_SLUGS = {
    "self-consumption_mode": 1,
    "economy_mode": 2,
    "backup_mode": 3,
    "off-grid_mode": 4,
    "self-consumption_+_max_power_mode": 5,
    "backup_+_max_power_mode": 6,
    "peak_shaving_mode": 7,
    "time_of_use_mode": 8,
}


def _legacy_reserve_soc_mode(unique_id: str) -> int | None:
    """Return the mode id a legacy slug-keyed reserve SOC unique id refers to."""
    marker = "_battery_reserve_soc_"
    if marker not in unique_id:
        return None
    _, _, suffix = unique_id.rpartition(marker)
    return LEGACY_RESERVE_SOC_MODE_SLUGS.get(suffix)


async def _async_migrate_reserve_soc_entities(
    hass: HomeAssistant, entry: ConfigEntry
) -> None:
    """Retire legacy slug-keyed reserve SOC entities.

    Two situations exist. If the modern mode-id entity was never created the
    legacy entry is renamed onto the new unique id, keeping the user's history
    and automations. If both exist - the common case, because the rename shipped
    without a migration and Home Assistant then suffixed the new entity with
    "_2" - the legacy entry is a dead duplicate and is removed.
    """
    registry = er.async_get(hass)
    entries = er.async_entries_for_config_entry(registry, entry.entry_id)
    known_unique_ids = {item.unique_id for item in entries}

    for item in entries:
        if item.domain != "number" or not item.unique_id:
            continue
        mode = _legacy_reserve_soc_mode(item.unique_id)
        if mode is None:
            continue

        marker = "_battery_reserve_soc_"
        prefix, _, _ = item.unique_id.rpartition(marker)
        new_unique_id = f"{prefix}{marker}{mode}"

        if new_unique_id in known_unique_ids:
            _LOGGER.info(
                "Removing superseded reserve SOC entity %s (unique id %s); "
                "it was replaced by the mode-id keyed entity",
                item.entity_id,
                item.unique_id,
            )
            registry.async_remove(item.entity_id)
            continue

        _LOGGER.info(
            "Migrating reserve SOC entity %s from unique id %s to %s",
            item.entity_id,
            item.unique_id,
            new_unique_id,
        )
        registry.async_update_entity(item.entity_id, new_unique_id=new_unique_id)
        known_unique_ids.add(new_unique_id)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Hoymiles Cloud from a config entry."""
    await _async_migrate_reserve_soc_entities(hass, entry)

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
    store = Store(hass, STORAGE_VERSION, entry_storage_key(STORAGE_KEY, entry.entry_id))
    stored_data = await store.async_load()

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

    if stored_data is None:
        legacy = await Store(hass, STORAGE_VERSION, STORAGE_KEY).async_load()
        stored_data = migrate_legacy_stations(legacy, set(stations))
        await store.async_save(stored_data)

    if _ensure_station_storage(stored_data, stations):
        await store.async_save(stored_data)

    static_station_cache: dict[str, dict[str, Any]] = {}
    static_station_cache_at: dict[str, float] = {}
    module_data_cache: dict[tuple[str, int], dict[str, float | None]] = {}
    module_data_cache_at: dict[tuple[str, int], float] = {}
    module_data_failures: set[tuple[str, int]] = set()
    request_limit = asyncio.Semaphore(4)

    async def _async_module_values(
        station_id: str,
        mi_id: int,
        channels: list[int],
    ) -> dict[int, dict[str, float | None]]:
        """Return per-channel module chart values, cached across polls.

        The cloud only refreshes plant telemetry every few minutes, so the day
        chart is re-fetched at most once per MODULE_DATA_CACHE_INTERVAL instead
        of on every coordinator poll. That keeps the extra requests off the
        shared 30 second update budget.
        """
        def _log_failure(cache_key: tuple[str, int], reason: Any) -> None:
            """Warn once per outage, then stay at debug.

            This path runs on every poll, so an endpoint that is simply
            unsupported for the account would otherwise flood the log.
            """
            message = "Failed to get module channel data for station %s port %s: %s"
            if cache_key in module_data_failures:
                _LOGGER.debug(message, cache_key[0], cache_key[1], reason)
                return
            module_data_failures.add(cache_key)
            _LOGGER.warning(message, cache_key[0], cache_key[1], reason)

        values_by_channel: dict[int, dict[str, float | None]] = {}
        now = time.monotonic()
        for channel in channels:
            cache_key = (station_id, channel)
            cached = module_data_cache.get(cache_key)
            if (
                cached is not None
                and now - module_data_cache_at.get(cache_key, 0)
                < MODULE_DATA_CACHE_INTERVAL
            ):
                if cached:
                    values_by_channel[channel] = cached
                continue
            try:
                values = await api.get_module_channel_data(
                    station_id, mi_id, channel, now=dt_util.now()
                )
            except Exception as err:
                _log_failure(cache_key, err)
                continue
            # An undecodable response comes back as an empty mapping. Cache it
            # too, so a broken endpoint is not re-requested on every poll.
            module_data_cache[cache_key] = values
            module_data_cache_at[cache_key] = now
            if not values:
                _log_failure(cache_key, "no usable series in response")
                continue
            module_data_failures.discard(cache_key)
            values_by_channel[channel] = values
        return values_by_channel

    async def _async_fetch_static_station_payload(station_id: str) -> dict[str, Any]:
        """Refresh inventory independently of the live telemetry deadline."""
        methods = {
            "station_info": api.get_station_details,
            "setting_rules": api.get_setting_rules,
            "dtus": api.get_dtus,
            "inverters": api.get_inverters,
            "batteries": api.get_batteries,
            "meters": api.get_meters,
            "microinverters": api.get_microinverters_by_stations,
            "eps_settings": api.get_eps_settings,
            "ai_status": api.get_ai_status,
            "firmware": api.get_firmware_status,
        }

        async def fetch(name: str, method: Any) -> tuple[str, Any]:
            try:
                async with request_limit:
                    return name, await asyncio.wait_for(method(station_id), timeout=8)
            except LiveDataAuthError:
                raise
            except Exception as err:
                _LOGGER.debug("Static %s read failed for station %s: %s", name, station_id, err)
                return name, None

        results = dict(await asyncio.gather(*(fetch(name, method) for name, method in methods.items())))
        previous = static_station_cache.get(station_id, {})
        station_info = results["station_info"] or previous.get("station_info", {})
        if station_info.get("name"):
            stations[station_id] = str(station_info["name"])
        old_devices = previous.get("devices", {})
        devices = DeviceInventory(
            dtus=results["dtus"] if results["dtus"] is not None else old_devices.get("dtus", []),
            inverters=results["inverters"] if results["inverters"] is not None else old_devices.get("inverters", []),
            batteries=results["batteries"] if results["batteries"] is not None else old_devices.get("batteries", []),
            meters=results["meters"] if results["meters"] is not None else old_devices.get("meters", []),
            microinverters=results["microinverters"] if results["microinverters"] is not None else old_devices.get("microinverters", {}),
        ).as_dict()
        def keep(name: str, wrapper: Any = None) -> dict[str, Any]:
            value = results[name]
            if value is None:
                return previous.get(name, {})
            return wrapper(value).as_dict() if wrapper else value
        return {
            "station_info": station_info,
            "setting_rules": keep("setting_rules", SettingRules),
            "devices": devices,
            "eps_settings": keep("eps_settings"),
            "ai_status": keep("ai_status", AIStatus),
            "firmware": keep("firmware", FirmwareStatus),
        }

    station_limit = asyncio.Semaphore(3)
    optional_failures: set[tuple[str, str]] = set()
    control_cache: dict[str, dict[str, Any]] = {}
    control_cache_at: dict[str, float] = {}

    async def _optional(station_id: str, name: str, method: Any, timeout: float = 6) -> Any:
        """A failed optional endpoint cannot fail station telemetry."""
        try:
            async with request_limit:
                result = await asyncio.wait_for(method(station_id), timeout=timeout)
        except LiveDataAuthError:
            raise
        except Exception as err:
            key = (station_id, name)
            log = _LOGGER.debug if key in optional_failures else _LOGGER.warning
            log("Failed to get %s for station %s: %s", name, station_id, err)
            optional_failures.add(key)
            return None
        optional_failures.discard((station_id, name))
        return result

    async def _station_update(station_id: str) -> tuple[str, dict[str, Any], bool]:
        async with station_limit:
            now = time.monotonic()
            if (station_id not in static_station_cache or
                    now - static_station_cache_at.get(station_id, 0) >= DEFAULT_STATIC_REFRESH_INTERVAL):
                static_station_cache[station_id] = await _async_fetch_static_station_payload(station_id)
                static_station_cache_at[station_id] = now
            static_payload = static_station_cache.get(station_id, {})

            names = ["real_time_data", "live_data", "pv_indicators", "load_indicators"]
            methods = [api.get_real_time_data, api.get_live_data, api.get_pv_indicators, api.get_load_indicators]
            if fetch_grid_indicators:
                names.append("grid_indicators")
                methods.append(api.get_grid_indicators)
            if fetch_energy_flow:
                names.append("energy_flow")
                methods.append(api.get_energy_flow)
            if fetch_eps_profit:
                names.append("eps_profit")
                methods.append(api.get_eps_profit)
            values = await asyncio.gather(*(
                _optional(station_id, name, method, 45 if name == "live_data" else 6)
                for name, method in zip(names, methods)
            ))
            payloads = dict(zip(names, values))
            real_time_data = payloads.get("real_time_data") or {}
            live_data = payloads.get("live_data") or {}
            live_fetched_at = time.time() if live_data else None
            pv_indicators = payloads.get("pv_indicators") or {}
            microinverters = static_payload.get("devices", {}).get("microinverters", {})
            pv_indicators = seed_missing_pv_channels(pv_indicators, microinverters)
            placeholders = find_placeholder_pv_channels(pv_indicators)
            if placeholders and len(microinverters) == 1:
                micro = next(iter(microinverters.values()))
                mi_id = micro.get("id") if isinstance(micro, dict) else None
                if mi_id is not None:
                    try:
                        module_values = await asyncio.wait_for(
                            _async_module_values(station_id, mi_id, placeholders), timeout=5
                        )
                    except asyncio.TimeoutError:
                        module_values = {}
                    if module_values:
                        pv_indicators = merge_missing_pv_channel_values(pv_indicators, module_values)

            if (station_id not in control_cache or
                    now - control_cache_at.get(station_id, 0) >= DEFAULT_STATIC_REFRESH_INTERVAL):
                battery, relay = await asyncio.gather(
                    _optional(station_id, "battery_settings", api.get_battery_settings, 12),
                    _optional(station_id, "relay_settings", api.get_relay_settings, 8),
                )
                control_cache[station_id] = {
                    "battery_settings": battery or {},
                    "relay_settings": relay or {},
                }
                control_cache_at[station_id] = now
            control = control_cache[station_id]
            battery_settings = control["battery_settings"]
            relay_settings = control["relay_settings"]
            grid_indicators = payloads.get("grid_indicators") or {}
            load_indicators = payloads.get("load_indicators") or {}
            energy_flow = payloads.get("energy_flow") or {}
            eps_profit = payloads.get("eps_profit") or {}
            station_stored_data = stored_data["stations"].setdefault(station_id, {})
            enhanced_battery_settings, changed = _enhance_battery_settings(
                battery_settings, station_stored_data
            )
            result = StationData(
                station_info=static_payload.get("station_info", {}),
                real_time_data=real_time_data,
                live_data=live_data,
                live_fetched_at=live_fetched_at,
                live_max_age=max(90, scan_interval * 2),
                telemetry_available=bool(real_time_data or live_data),
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
                schedule_editor=build_schedule_editor_state(enhanced_battery_settings, station_stored_data),
                capabilities=build_station_capabilities(
                    real_time_data=real_time_data,
                    pv_indicators=pv_indicators,
                    battery_settings=enhanced_battery_settings,
                    microinverters_data=microinverters,
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
            return station_id, result, changed

    async def async_update_data():
        """Refresh stations independently and keep failed stations unavailable."""
        if api.is_token_expired() and not await api.authenticate():
            raise ConfigEntryAuthFailed(
                "Hoymiles authentication failed: "
                f"{api.last_auth_status} - {api.last_auth_message}"
            )
        results = await asyncio.gather(
            *(_station_update(station_id) for station_id in stations),
            return_exceptions=True,
        )
        refreshed: dict[str, dict[str, Any]] = {}
        should_save = False
        for station_id, result in zip(stations, results):
            if isinstance(result, LiveDataAuthError):
                raise ConfigEntryAuthFailed("Hoymiles Cloud session is no longer authorized") from result
            if isinstance(result, BaseException):
                _LOGGER.warning("Station %s refresh failed: %s", station_id, result)
                previous = (coordinator.data or {}).get(station_id, {})
                refreshed[station_id] = {
                    **previous,
                    "real_time_data": {},
                    "live_data": {},
                    "live_fetched_at": None,
                    "telemetry_available": False,
                    "pv_indicators": {},
                    "grid_indicators": {},
                    "load_indicators": {},
                    "energy_flow": {},
                    "eps_profit": {},
                }
            else:
                _, refreshed[station_id], changed = result
                should_save = should_save or changed
        if should_save:
            await store.async_save(stored_data)
        if not any(item.get("telemetry_available") for item in refreshed.values()):
            raise UpdateFailed("No station telemetry could be refreshed")
        return refreshed

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
        "control_cache_at": control_cache_at,
        "invalidate_control_cache": lambda station_id: control_cache_at.pop(station_id, None),
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

        control_cache_at.pop(station_id, None)
        await coordinator.async_refresh()
        if not coordinator.last_update_success or not battery_settings_readable(
            (coordinator.data or {}).get(station_id, {}).get("battery_settings", {})
        ):
            raise HomeAssistantError(
                "Schedule write completed, but fresh settings could not be read; the draft was retained"
            )
        await async_load_schedule_draft(station_id, mode)

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
    original_options = dict(entry.options)

    async def options_update_listener(hass: HomeAssistant, updated_entry: ConfigEntry) -> None:
        """Only options require listener reload; reauth performs its own reload."""
        if dict(updated_entry.options) != original_options:
            await hass.config_entries.async_reload(updated_entry.entry_id)

    entry.async_on_unload(entry.add_update_listener(options_update_listener))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id, None)
        await _async_unregister_services(hass)
    return unload_ok
