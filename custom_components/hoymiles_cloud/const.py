"""Constants for the Hoymiles Cloud integration."""

DOMAIN = "hoymiles_cloud"

# Storage constants
STORAGE_VERSION = 1
STORAGE_KEY = f"{DOMAIN}_data"

# API base URLs
API_BASE_URL = "https://neapi.hoymiles.com"
API_EU_BASE_URL = "https://euapi.hoymiles.com"
API_STREAM_BASE_URL = "https://eurt.hoymiles.com"

# Authentication endpoints
API_AUTH_URL = f"{API_BASE_URL}/iam/pub/0/auth/login"
API_AUTH_PRE_INSP_URL = f"{API_BASE_URL}/iam/pub/3/auth/pre-insp"
API_AUTH_V3_URL = f"{API_BASE_URL}/iam/pub/3/auth/login"
API_USER_ME_URL = f"{API_BASE_URL}/iam/api/1/user/me"

# Station and device endpoints
API_STATIONS_URL = f"{API_BASE_URL}/pvm/api/0/station/select_by_page"
API_STATION_DETAILS_URL = f"{API_BASE_URL}/pvm/api/0/station/find"
API_STATION_SETTING_RULE_URL = f"{API_BASE_URL}/pvm/api/0/station/setting_rule"
API_STATION_GET_SD_URI_URL = f"{API_BASE_URL}/pvm/api/0/station/get_sd_uri"
API_STATION_USER_SETTING_URL = f"{API_BASE_URL}/pvm/api/0/station/setting/get_user_setting"
API_STATION_PRICE_URL = f"{API_BASE_URL}/pvm/api/0/station/price/find"
API_STATION_BATTERY_CONFIG_URL = f"{API_BASE_URL}/pvm/api/0/station/setting/battery_config"
API_MICROINVERTERS_URL = f"{API_BASE_URL}/pvm/api/0/dev/micro/select_by_station"
API_MICRO_DETAIL_URL = f"{API_BASE_URL}/pvm/api/0/dev/micro/find"
API_DTUS_URL = f"{API_BASE_URL}/pvm/api/0/dev/dtu/select_by_station"
API_INVERTERS_URL = f"{API_BASE_URL}/pvm/api/0/dev/inverter/select_by_station"
API_BATTERIES_URL = f"{API_BASE_URL}/pvm/api/0/dev/battery/select_by_station"
API_METERS_URL = f"{API_BASE_URL}/pvm/api/0/dev/meter/select_by_station"

# Telemetry endpoints
API_REAL_TIME_DATA_URL = f"{API_BASE_URL}/pvm-data/api/0/station/data/count_station_real_data"
API_ENERGY_FLOW_STATS_URL = f"{API_BASE_URL}/pvm-data/api/0/station/data_fd/stat_g_a"
API_INDICATORS_URL = f"{API_BASE_URL}/pvm-data/api/0/indicators/data/select_real_indicators_data"

# Battery / relay control endpoints
API_BATTERY_SETTINGS_READ_URL = f"{API_BASE_URL}/pvm-ctl/api/0/dev/setting/read"
API_BATTERY_SETTINGS_WRITE_URL = f"{API_BASE_URL}/pvm-ctl/api/0/dev/setting/write"
API_BATTERY_SETTINGS_STATUS_URL = f"{API_BASE_URL}/pvm-ctl/api/0/dev/setting/status"

# Ancillary endpoints
API_EPS_SETTINGS_URL = f"{API_BASE_URL}/eps/api/0/setting/g_a"
API_EPS_PROFIT_URL = f"{API_BASE_URL}/eps/api/0/record/stat_a"
API_AI_STATUS_URL = f"{API_BASE_URL}/pvm-ai/api/0/station/sar_g_c"
API_FIRMWARE_STATUS_URL = f"{API_BASE_URL}/pvm/api/0/upgrade/compare"

# Authentication modes / client profiles
AUTH_MODE_AUTO = "auto"
AUTH_MODE_WEB_V3 = "web_v3"
AUTH_MODE_INSTALLER_V3 = "installer_v3"
AUTH_MODE_HOME_V3 = "home_v3"
AUTH_MODE_LEGACY_V0 = "legacy_v0"

CLIENT_PROFILE_WEB = "web"
CLIENT_PROFILE_INSTALLER = "installer"
CLIENT_PROFILE_HOME = "home"

DEFAULT_WEB_USER_AGENT = "HomeAssistant-HoymilesCloud"
DEFAULT_INSTALLER_USER_AGENT = "S-Miles Installer"
DEFAULT_HOME_USER_AGENT = "S-Miles Home"
DEFAULT_INSTALLER_APP_VERSION = "3.7.1"
DEFAULT_HOME_APP_VERSION = "2.8.0"

AUTH_PROFILE_DEFAULTS = {
    CLIENT_PROFILE_WEB: {
        "user_agent": DEFAULT_WEB_USER_AGENT,
        "app_version": None,
        "x_client_type": None,
    },
    CLIENT_PROFILE_INSTALLER: {
        "user_agent": DEFAULT_INSTALLER_USER_AGENT,
        "app_version": DEFAULT_INSTALLER_APP_VERSION,
        "x_client_type": "mobile",
    },
    CLIENT_PROFILE_HOME: {
        "user_agent": DEFAULT_HOME_USER_AGENT,
        "app_version": DEFAULT_HOME_APP_VERSION,
        "x_client_type": "mobile",
    },
}

AUTH_MODE_TO_PROFILE = {
    AUTH_MODE_WEB_V3: CLIENT_PROFILE_WEB,
    AUTH_MODE_INSTALLER_V3: CLIENT_PROFILE_INSTALLER,
    AUTH_MODE_HOME_V3: CLIENT_PROFILE_HOME,
}

AUTH_MODE_OPTIONS = {
    AUTH_MODE_AUTO: "Auto-detect",
    AUTH_MODE_WEB_V3: "S-Miles Cloud Web",
    AUTH_MODE_INSTALLER_V3: "S-Miles Installer",
    AUTH_MODE_HOME_V3: "S-Miles Home",
    AUTH_MODE_LEGACY_V0: "Legacy v0",
}

# Battery modes
BATTERY_MODE_SELF_CONSUMPTION = 1
BATTERY_MODE_ECONOMY = 2
BATTERY_MODE_BACKUP = 3
BATTERY_MODE_OFF_GRID = 4
BATTERY_MODE_SELF_CONSUMPTION_MAX_POWER = 5
BATTERY_MODE_BACKUP_MAX_POWER = 6
BATTERY_MODE_PEAK_SHAVING = 7
BATTERY_MODE_TIME_OF_USE = 8

BATTERY_MODE_IDS = (
    BATTERY_MODE_SELF_CONSUMPTION,
    BATTERY_MODE_ECONOMY,
    BATTERY_MODE_BACKUP,
    BATTERY_MODE_OFF_GRID,
    BATTERY_MODE_SELF_CONSUMPTION_MAX_POWER,
    BATTERY_MODE_BACKUP_MAX_POWER,
    BATTERY_MODE_PEAK_SHAVING,
    BATTERY_MODE_TIME_OF_USE,
)

BATTERY_SCHEDULE_MODE_IDS = (
    BATTERY_MODE_ECONOMY,
    BATTERY_MODE_TIME_OF_USE,
)

BATTERY_POWER_LIMIT_MODE_IDS = (
    BATTERY_MODE_SELF_CONSUMPTION_MAX_POWER,
    BATTERY_MODE_BACKUP_MAX_POWER,
)

BATTERY_MODES = {
    BATTERY_MODE_SELF_CONSUMPTION: "Self-Consumption Mode",
    BATTERY_MODE_ECONOMY: "Economy Mode",
    BATTERY_MODE_BACKUP: "Backup Mode",
    BATTERY_MODE_OFF_GRID: "Off-Grid Mode",
    BATTERY_MODE_SELF_CONSUMPTION_MAX_POWER: "Self-Consumption + Max Power Mode",
    BATTERY_MODE_BACKUP_MAX_POWER: "Backup + Max Power Mode",
    BATTERY_MODE_PEAK_SHAVING: "Peak Shaving Mode",
    BATTERY_MODE_TIME_OF_USE: "Time of Use Mode",
}

# Action IDs
BATTERY_SETTINGS_ACTION_ID = 1013
RELAY_SETTINGS_ACTION_ID = 1014
INVERTER_CONFIG_ACTION_ID = 1030

# Async command status codes
BATTERY_SETTINGS_STATUS_RUNNING = 2
BATTERY_SETTINGS_STATUS_SUCCESS = 0

# Indicator types
INDICATOR_TYPE_LOAD = 1
INDICATOR_TYPE_GRID = 2
INDICATOR_TYPE_PV = 4
INDICATOR_TYPE_METER_ES = 5

# Energy-flow stats types
ENERGY_FLOW_STAT_TYPE_OVERVIEW = 1
ENERGY_FLOW_STAT_TYPE_BATTERY = 4
ENERGY_FLOW_STAT_TYPE_GRID = 5
ENERGY_FLOW_STAT_TYPE_FULL = 6

# Meter locations
METER_LOCATION_GRID = 2
METER_LOCATION_BATTERY = 4
METER_LOCATION_NAMES = {
    METER_LOCATION_GRID: "Grid Meter",
    METER_LOCATION_BATTERY: "Battery Meter",
}

# Defaults
DEFAULT_SCAN_INTERVAL = 60  # seconds
DEFAULT_STATIC_REFRESH_INTERVAL = 300  # seconds
DEFAULT_FETCH_GRID_INDICATORS = True
DEFAULT_FETCH_ENERGY_FLOW = True
DEFAULT_FETCH_EPS_PROFIT = True

# Configuration
CONF_STATION_ID = "station_id"
CONF_AUTH_MODE = "auth_mode"
CONF_APP_VERSION = "app_version"
CONF_FETCH_GRID_INDICATORS = "fetch_grid_indicators"
CONF_FETCH_ENERGY_FLOW = "fetch_energy_flow"
CONF_FETCH_EPS_PROFIT = "fetch_eps_profit"

# Entity categories
ENTITY_CATEGORY_DIAGNOSTIC = "diagnostic"
ENTITY_CATEGORY_CONFIG = "config"

# Units of measurement
POWER_WATT = "W"
ENERGY_WATT_HOUR = "Wh"
PERCENTAGE = "%"