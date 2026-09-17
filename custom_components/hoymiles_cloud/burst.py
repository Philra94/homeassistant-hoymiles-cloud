"""Independent, bounded burst polling and pure power-source selection.

Only PV and verified hybrid charger watts are mapped. Energy counters and grid,
battery and load semantics deliberately remain on their established sources.
"""
from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime, timezone
import logging
import math
import time
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

_LOGGER = logging.getLogger(__name__)
MIN_DELAY = 1.5
DEFAULT_DELAY = 10.0
MAX_BACKOFF = 300.0


def number(value: Any) -> float | None:
    """Accept finite, nonnegative watts; never turn absent fields into zero."""
    if isinstance(value, bool):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return result if math.isfinite(result) and result >= 0 else None


def poll_delay(data: dict[str, Any]) -> float:
    """Honor server delays, including values longer than the usual 10 seconds."""
    delay = number(data.get("dly"))
    return max(MIN_DELAY, delay / 1000) if delay and delay > 0 else DEFAULT_DELAY


def inverter_targets(station: dict[str, Any]) -> dict[str, int]:
    """Map explicitly identified microinverter serials to declared port counts."""
    targets = {}
    for item in station.get("devices", {}).get("microinverters", {}).values():
        if not isinstance(item, dict):
            continue
        serial = item.get("sn") or item.get("micro_sn")
        if not isinstance(serial, str) or not serial.strip():
            continue
        rule = item.get("rule")
        port = rule.get("port") if isinstance(rule, dict) else None
        # Unknown port count permits AC telemetry but must not invent strings.
        count = number(port)
        targets[serial] = int(count) if count is not None and count.is_integer() and 1 <= count <= 32 else 0
    return targets


def _timestamp_current(data: dict[str, Any], station: dict[str, Any], now: float, max_age: float) -> bool:
    """Check vendor time only with an explicit station timezone; never use HA's."""
    stamp = data.get("t")
    info = station.get("station_info", {})
    zone = info.get("timezone")
    zone = zone.get("name") if isinstance(zone, dict) else zone
    if not isinstance(stamp, str) or not isinstance(zone, str):
        return True
    try:
        local = datetime.strptime(stamp, "%Y-%m-%d %H:%M:%S").replace(tzinfo=ZoneInfo(zone))
    except (ValueError, ZoneInfoNotFoundError):
        return True
    age = now - local.astimezone(timezone.utc).timestamp()
    return -30 <= age <= max_age


@dataclass(frozen=True)
class Sample:
    """One endpoint sample; monotonic times are local and never persisted."""
    data: dict[str, Any]
    received: float
    changed: float
    delay: float
    state: str

    def current(self, now: float) -> bool:
        return self.state == "live" and 0 <= now - self.received <= max(30, self.delay * 3) and now - self.changed <= max(30, self.delay * 3)


def select_power(station: dict[str, Any], key: str, *, serial: str | None = None,
                 port: int | None = None, now: float | None = None) -> tuple[bool, float | None]:
    """Return (owns value, watts). Offline owns None; errors allow slow fallback."""
    if key == "pv_string_power" and serial is None:
        inventory = station.get("devices", {}).get("microinverters", {})
        targets = inverter_targets(station)
        if len(inventory) != 1 or len(targets) != 1:
            return False, None
        target, count = next(iter(targets.items()))
        if count == 0:
            return False, None
        values = [select_power(station, "pv_power", serial=target, port=index, now=now)
                  for index in range(1, count + 1)]
        if not all(handled for handled, _ in values):
            return False, None
        return True, sum(value for _, value in values) if all(value is not None for _, value in values) else None
    snapshot = station.get("burst", {})
    sample = snapshot.get("inverters" if serial else "station")
    if not isinstance(sample, Sample):
        return False, None
    now = time.monotonic() if now is None else now
    # An explicitly disconnected stream must not resurrect cached slow watts.
    if sample.state in {"offline", "stale"}:
        return True, None
    if not sample.current(now):
        return False, None
    data = sample.data
    if serial:
        for item in data.get("mis", []):
            if isinstance(item, dict) and item.get("sn") == serial:
                return True, number(item.get(f"p{port}" if port else "pac"))
        return True, None
    if key == "pv_power":
        if isinstance(data.get("power"), dict):
            return True, number(data["power"].get("pv"))
        if isinstance(data.get("es"), dict):
            return True, number(data["es"].get("pp"))
    if key == "ev_charger_power" and isinstance(data.get("es"), dict):
        icon = data.get("icon")
        if isinstance(icon, dict) and icon.get("pile") in (1, "1"):
            return True, number(data["es"].get("sp"))
        return True, None
    return False, None


def select_channel_power(station: dict[str, Any], channel: int, *, now: float | None = None) -> tuple[bool, float | None]:
    """Reuse legacy channel IDs only for the proven single-inverter mapping."""
    inventory = station.get("devices", {}).get("microinverters", {})
    targets = inverter_targets(station)
    if len(inventory) != 1 or len(targets) != 1:
        return False, None
    serial, count = next(iter(targets.items()))
    if not 1 <= channel <= count:
        return False, None
    return select_power(station, "pv_power", serial=serial, port=channel, now=now)


class BurstPoller:
    """One cancellable loop per station, independent of slow coordinator timing."""

    def __init__(self, api: Any, stations: Callable[[], dict[str, dict[str, Any]]],
                 publish: Callable[[], None], auth_failed: Callable[[], None], *,
                 clock: Callable[[], float] = time.monotonic,
                 wall_clock: Callable[[], float] = time.time) -> None:
        self.api, self.stations, self.publish, self.auth_failed = api, stations, publish, auth_failed
        self.clock, self.wall_clock = clock, wall_clock
        self.samples: dict[str, dict[str, Sample]] = {}
        self.failures: dict[tuple[str, str], int] = {}
        self._tasks: dict[str, asyncio.Task] = {}
        self._due: dict[tuple[str, str], float] = {}
        self._limit = asyncio.Semaphore(2)
        self._expiry_task: asyncio.Task | None = None
        self._stopped = False
        self._auth_failed = False

    def start(self) -> None:
        """Start only after platforms are loaded; callers must await stop on unload."""
        if self._expiry_task is None and not self._stopped:
            self._expiry_task = asyncio.create_task(self._expire_loop(), name="hoymiles-burst-expiry")
        for sid in self.stations():
            if sid not in self._tasks and not self._stopped:
                self._tasks[sid] = asyncio.create_task(self._run(sid), name="hoymiles-burst")

    async def stop(self) -> None:
        self._stopped = True
        tasks = list(self._tasks.values())
        if self._expiry_task is not None:
            tasks.append(self._expiry_task)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        self._tasks.clear()
        self._expiry_task = None

    def expire(self) -> None:
        """Publish expiry even while all network requests are still in flight."""
        changed = False
        for scopes in self.samples.values():
            for scope, sample in list(scopes.items()):
                if sample.state == "live" and not sample.current(self.clock()):
                    scopes[scope] = replace(sample, state="stale")
                    changed = True
        if changed:
            self.publish()

    async def _expire_loop(self) -> None:
        while not self._stopped and not self._auth_failed:
            await asyncio.sleep(MIN_DELAY)
            self.expire()

    async def _run(self, sid: str) -> None:
        while not self._stopped and not self._auth_failed:
            delay = await self.poll_once(sid)
            await asyncio.sleep(delay)

    async def poll_once(self, sid: str) -> float:
        """Fetch each supported scope independently; a device error cannot erase totals."""
        from .hoymiles_api import LiveDataAuthError

        station = self.stations().get(sid, {})
        serials = list(inverter_targets(station))
        scopes = [("station", None)] + ([("inverters", serials)] if serials else [])
        if not serials:
            self.samples.get(sid, {}).pop("inverters", None)
        for scope, requested in scopes:
            if self._stopped or self._auth_failed:
                break
            key = (sid, scope)
            if self._due.get(key, 0) > self.clock():
                continue
            previous = self.samples.get(sid, {}).get(scope)
            try:
                async with self._limit:
                    data = await asyncio.wait_for(self.api.get_burst_data(sid, serials=requested), timeout=45)
                if self._stopped or self._auth_failed:
                    break
                now = self.clock()
                delay = poll_delay(data)
                changed = now
                if previous and data.get("t") is not None and data.get("t") == previous.data.get("t"):
                    changed = previous.changed
                age_limit = max(30, delay * 3)
                state = "live" if data.get("con") == 1 else "offline"
                if state == "live" and (now - changed > age_limit or not _timestamp_current(data, station, self.wall_clock(), age_limit)):
                    state = "stale"
                self.samples.setdefault(sid, {})[scope] = Sample(data, now, changed, delay, state)
                self.failures.pop(key, None)
                self._due[key] = self.clock() + (max(delay, DEFAULT_DELAY) if state != "live" else delay)
            except LiveDataAuthError:
                if not self._auth_failed:
                    self._auth_failed = True
                    self.samples.clear()
                    self.auth_failed()
                    self.publish()
                break
            except Exception:
                # Do not log exceptions that might contain signed URLs or serials.
                count = self.failures.get(key, 0) + 1
                self.failures[key] = count
                _LOGGER.debug("Burst %s request failed (consecutive failures: %s)", scope, count)
                # Keep an offline verdict until a connected sample arrives. A network
                # error cannot prove that yesterday's slow power is current again.
                if previous is None or previous.state != "offline":
                    self.samples.setdefault(sid, {}).pop(scope, None)
                self._due[key] = self.clock() + min(MAX_BACKOFF, DEFAULT_DELAY * 2 ** min(count - 1, 5))
            self.publish()
        return max(0.0, min((self._due.get((sid, scope), self.clock() + DEFAULT_DELAY) - self.clock() for scope, _ in scopes), default=DEFAULT_DELAY))
