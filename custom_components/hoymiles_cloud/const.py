"""Constants for the Hoymiles Cloud integration."""

DOMAIN = "hoymiles_cloud"

# Storage constants
STORAGE_VERSION = 1
STORAGE_KEY = f"{DOMAIN}_data"

# API Constants
API_BASE_URL = "https://neapi.hoymiles.com"
API_AUTH_URL = f"{API_BASE_URL}/iam/pub/0/auth/login"
API_STATIONS_URL = f"{API_BASE_URL}/pvm/api/0/station/select_by_page"
API_REAL_TIME_DATA_URL = f"{API_BASE_URL}/pvm-data/api/0/station/data/count_station_real_data" 
API_MICROINVERTERS_URL = f"{API_BASE_URL}/pvm/api/0/dev/micro/select_by_station"
API_MICRO_DETAIL_URL = f"{API_BASE_URL}/pvm/api/0/dev/micro/find"
API_PV_INDICATORS_URL = f"{API_BASE_URL}/pvm-data/api/0/indicators/data/select_real_indicators_data"
API_BATTERY_SETTINGS_READ_URL = f"{API_BASE_URL}/pvm-ctl/api/0/dev/setting/read"
API_BATTERY_SETTINGS_WRITE_URL = f"{API_BASE_URL}/pvm-ctl/api/0/dev/setting/write"
API_BATTERY_SETTINGS_STATUS_URL = f"{API_BASE_URL}/pvm-ctl/api/0/dev/setting/status"

# Battery Modes
BATTERY_MODE_SELF_CONSUMPTION = 1
BATTERY_MODE_TIME_OF_USE = 8
BATTERY_MODE_BACKUP = 3
BATTERY_MODE_OFF_GRID = 4
BATTERY_MODE_PEAK_SHAVING = 7
BATTERY_MODE_ECONOMY = 2
BATTERY_MODE_CUSTOM = 8  # Time of Use Mode is the new Custom Mode

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