"""Constants for the Hoymiles Cloud integration."""

DOMAIN = "hoymiles_cloud"

# Storage constants
STORAGE_VERSION = 1
STORAGE_KEY = f"{DOMAIN}_data"

# API Constants
API_BASE_URL = "https://neapi.hoymiles.com"
API_AUTH_URL = f"{API_BASE_URL}/iam/pub/0/auth/login"
API_AUTH_PRE_INSP_URL = f"{API_BASE_URL}/iam/pub/3/auth/pre-insp"
API_AUTH_V3_URL = f"{API_BASE_URL}/iam/pub/3/auth/login"
API_USER_ME_URL = f"{API_BASE_URL}/iam/api/1/user/me"
API_STATIONS_URL = f"{API_BASE_URL}/pvm/api/0/station/select_by_page"
API_REAL_TIME_DATA_URL = f"{API_BASE_URL}/pvm-data/api/0/station/data/count_station_real_data" 
API_MICROINVERTERS_URL = f"{API_BASE_URL}/pvm/api/0/dev/micro/select_by_station"
API_MICRO_DETAIL_URL = f"{API_BASE_URL}/pvm/api/0/dev/micro/find"
API_PV_INDICATORS_URL = f"{API_BASE_URL}/pvm-data/api/0/indicators/data/select_real_indicators_data"
API_BATTERY_SETTINGS_READ_URL = f"{API_BASE_URL}/pvm-ctl/api/0/dev/setting/read"
API_BATTERY_SETTINGS_WRITE_URL = f"{API_BASE_URL}/pvm-ctl/api/0/dev/setting/write"
API_BATTERY_SETTINGS_STATUS_URL = f"{API_BASE_URL}/pvm-ctl/api/0/dev/setting/status"

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

# Battery Modes
BATTERY_MODE_SELF_CONSUMPTION = 1
BATTERY_MODE_ECONOMY = 2
BATTERY_MODE_BACKUP = 3
BATTERY_MODE_OFF_GRID = 4
BATTERY_MODE_PEAK_SHAVING = 7
BATTERY_MODE_TIME_OF_USE = 8

BATTERY_MODE_IDS = (
    BATTERY_MODE_SELF_CONSUMPTION,
    BATTERY_MODE_ECONOMY,
    BATTERY_MODE_BACKUP,
    BATTERY_MODE_OFF_GRID,
    BATTERY_MODE_PEAK_SHAVING,
    BATTERY_MODE_TIME_OF_USE,
)

BATTERY_SCHEDULE_MODE_IDS = (
    BATTERY_MODE_ECONOMY,
    BATTERY_MODE_TIME_OF_USE,
)

BATTERY_MODES = {
    BATTERY_MODE_SELF_CONSUMPTION: "Self-Consumption Mode",
    BATTERY_MODE_ECONOMY: "Economy Mode",
    BATTERY_MODE_BACKUP: "Backup Mode",
    BATTERY_MODE_OFF_GRID: "Off-Grid Mode",
    BATTERY_MODE_PEAK_SHAVING: "Peak Shaving Mode",
    BATTERY_MODE_TIME_OF_USE: "Time of Use Mode",
}

# Default settings
DEFAULT_SCAN_INTERVAL = 60  # seconds

# Configuration
CONF_STATION_ID = "station_id"
CONF_AUTH_MODE = "auth_mode"
CONF_APP_VERSION = "app_version"

# Sensor types
SENSOR_TYPE_POWER = "power"
SENSOR_TYPE_ENERGY = "energy"
SENSOR_TYPE_SOC = "soc"
SENSOR_TYPE_GRID = "grid"
SENSOR_TYPE_LOAD = "load"

SETTING_TYPE_MODE = "mode"
SETTING_TYPE_RESERVE_SOC = "reserve_soc"

# Entity category
ENTITY_CATEGORY_DIAGNOSTIC = "diagnostic"
ENTITY_CATEGORY_CONFIG = "config"

# Units of measurement
POWER_WATT = "W"
ENERGY_WATT_HOUR = "Wh"
PERCENTAGE = "%" 