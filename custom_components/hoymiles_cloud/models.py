"""Typed runtime models for the Hoymiles Cloud integration."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(slots=True)
class DeviceInventory:
    """Known devices attached to one Hoymiles station."""

    dtus: list[dict[str, Any]] = field(default_factory=list)
    inverters: list[dict[str, Any]] = field(default_factory=list)
    batteries: list[dict[str, Any]] = field(default_factory=list)
    meters: list[dict[str, Any]] = field(default_factory=list)
    microinverters: dict[str, dict[str, Any]] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable representation."""
        return asdict(self)


@dataclass(slots=True)
class EnergyFlow:
    """Aggregated station energy-flow stats."""

    raw: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable representation."""
        return dict(self.raw)


@dataclass(slots=True)
class EPSProfit:
    """Profit and spend metrics from the EPS service."""

    raw: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable representation."""
        return dict(self.raw)


@dataclass(slots=True)
class SettingRules:
    """Station capability flags from the settings-rule endpoint."""

    raw: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable representation."""
        return dict(self.raw)


@dataclass(slots=True)
class AIStatus:
    """AI/compound mode metadata for a station."""

    raw: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable representation."""
        return dict(self.raw)


@dataclass(slots=True)
class FirmwareStatus:
    """Firmware availability metadata for a station."""

    raw: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable representation."""
        return dict(self.raw)


@dataclass(slots=True)
class StationData:
    """Complete coordinator payload for one station."""

    station_info: dict[str, Any] = field(default_factory=dict)
    real_time_data: dict[str, Any] = field(default_factory=dict)
    energy_flow: dict[str, Any] = field(default_factory=dict)
    pv_indicators: dict[str, Any] = field(default_factory=dict)
    grid_indicators: dict[str, Any] = field(default_factory=dict)
    load_indicators: dict[str, Any] = field(default_factory=dict)
    battery_settings: dict[str, Any] = field(default_factory=dict)
    relay_settings: dict[str, Any] = field(default_factory=dict)
    eps_settings: dict[str, Any] = field(default_factory=dict)
    eps_profit: dict[str, Any] = field(default_factory=dict)
    ai_status: dict[str, Any] = field(default_factory=dict)
    setting_rules: dict[str, Any] = field(default_factory=dict)
    devices: dict[str, Any] = field(default_factory=dict)
    firmware: dict[str, Any] = field(default_factory=dict)
    schedule_editor: dict[str, Any] = field(default_factory=dict)
    capabilities: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        """Return the coordinator payload format used by entities."""
        return asdict(self)
