"""Authentication helpers for the Hoymiles Cloud integration."""
from __future__ import annotations

from dataclasses import dataclass


AUTH_ERROR_APP_UPDATE_REQUIRED = "app_update_required"
AUTH_ERROR_S_MILES_HOME_REQUIRED = "s_miles_home_required"
AUTH_ERROR_NO_ACCESSIBLE_STATIONS = "no_accessible_stations"
AUTH_ERROR_INVALID_AUTH = "invalid_auth"
AUTH_ERROR_UNKNOWN = "unknown"


@dataclass(slots=True)
class AuthAttempt:
    """Result of a single authentication strategy attempt."""

    method: str
    client_profile: str
    success: bool
    status: str | None = None
    message: str | None = None
    token: str | None = None
    app_version: str | None = None
    variant: str | None = None

    @property
    def error_key(self) -> str:
        """Return a normalized error key for this attempt."""
        return classify_auth_failure(self.status, self.message)

    def summary(self) -> str:
        """Return a compact human-readable summary for diagnostics."""
        version = f"/{self.app_version}" if self.app_version else ""
        outcome = "ok" if self.success else f"{self.status or '?'}:{self.message or '<no message>'}"
        variant = f" ({self.variant})" if self.variant else ""
        return f"{self.method}[{self.client_profile}{version}]{variant} -> {outcome}"


def classify_auth_failure(status: str | None, message: str | None) -> str:
    """Classify a Hoymiles auth failure into a config-flow friendly key."""
    text = (message or "").lower()
    if "version is low" in text or "update to the latest version" in text:
        return AUTH_ERROR_APP_UPDATE_REQUIRED
    if "s-miles home" in text:
        return AUTH_ERROR_S_MILES_HOME_REQUIRED
    if status or message:
        return AUTH_ERROR_INVALID_AUTH
    return AUTH_ERROR_UNKNOWN


def choose_preferred_failure(attempts: list[AuthAttempt]) -> AuthAttempt | None:
    """Choose the most useful auth failure to surface to the user."""
    if not attempts:
        return None

    priority = {
        AUTH_ERROR_APP_UPDATE_REQUIRED: 4,
        AUTH_ERROR_S_MILES_HOME_REQUIRED: 3,
        AUTH_ERROR_INVALID_AUTH: 2,
        AUTH_ERROR_UNKNOWN: 1,
    }
    return max(attempts, key=lambda attempt: priority.get(attempt.error_key, 0))


def summarize_auth_attempts(attempts: list[AuthAttempt]) -> str:
    """Return a compact one-line summary of all auth attempts."""
    if not attempts:
        return "<no attempts>"
    return "; ".join(attempt.summary() for attempt in attempts)


def auth_error_to_config_error(error_key: str | None) -> str:
    """Map a normalized auth error key to a config flow error key."""
    if error_key == AUTH_ERROR_APP_UPDATE_REQUIRED:
        return AUTH_ERROR_APP_UPDATE_REQUIRED
    if error_key == AUTH_ERROR_S_MILES_HOME_REQUIRED:
        return AUTH_ERROR_S_MILES_HOME_REQUIRED
    if error_key == AUTH_ERROR_NO_ACCESSIBLE_STATIONS:
        return AUTH_ERROR_NO_ACCESSIBLE_STATIONS
    if error_key == AUTH_ERROR_INVALID_AUTH:
        return AUTH_ERROR_INVALID_AUTH
    return AUTH_ERROR_UNKNOWN
