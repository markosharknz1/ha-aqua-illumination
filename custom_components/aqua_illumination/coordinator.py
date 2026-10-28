"""Polling coordinator + the write helpers every entity shares."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import (
    AquaIlluminationClient,
    AquaIlluminationError,
    percent_to_raw,
    validate_schedule,
)
from .const import (
    CLOCK_DRIFT_SECONDS,
    DOMAIN,
    SCHEDULE_REFRESH_EVERY,
)

_LOGGER = logging.getLogger(__name__)


class AquaCoordinator(DataUpdateCoordinator[dict]):
    """Holds the light's state: colors, schedule flag, temperature, clock."""

    def __init__(
        self, hass: HomeAssistant, client: AquaIlluminationClient,
        identity: dict, poll_seconds: int, auto_clock: bool,
    ) -> None:
        super().__init__(
            hass, _LOGGER, name=f"{DOMAIN} {identity['serial_number']}",
            update_interval=timedelta(seconds=poll_seconds),
        )
        self.client = client
        self.identity = identity
        self.serial: str = identity["serial_number"]
        self.auto_clock = auto_clock
        self._polls = 0
        self._schedule: dict | None = None

    @property
    def channels(self) -> list[str]:
        return list((self.data or {}).get("colors", {}))

    async def _async_update_data(self) -> dict:
        try:
            colors = await self.client.colors()
            enabled = await self.client.schedule_enabled()
            temperature = await self.client.temperature()
            clock = await self.client.time()
            if self._schedule is None or self._polls % SCHEDULE_REFRESH_EVERY == 0:
                self._schedule = await self.client.schedule()
        except AquaIlluminationError as err:
            raise UpdateFailed(str(err)) from err
        self._polls += 1
        lunar = None
        try:
            lunar = await self.client.lunar()
        except AquaIlluminationError:
            pass  # firmware without moonlight support
        data = {
            "colors": colors, "schedule_enabled": enabled,
            "temperature": temperature, "clock": clock,
            "schedule": self._schedule, "lunar": lunar,
        }
        if self.auto_clock and self._clock_drift(clock) > CLOCK_DRIFT_SECONDS:
            try:
                await self.async_sync_clock()
                data["clock"] = await self.client.time()
            except AquaIlluminationError as err:
                _LOGGER.warning("Clock sync failed: %s", err)
        return data

    # -- clock ---------------------------------------------------------
    def _zone(self, clock: dict) -> ZoneInfo:
        for name in (clock.get("location"), self.hass.config.time_zone):
            try:
                return ZoneInfo(str(name).replace(" ", "_"))
            except (ZoneInfoNotFoundError, ValueError, TypeError):
                continue
        return ZoneInfo("UTC")

    def _clock_drift(self, clock: dict) -> float:
        """Seconds between the light's wall clock and the real local time."""
        zone = self._zone(clock)
        try:
            device = datetime(
                clock["year"], clock["month"] + 1, clock["day"],
                clock["hours"], clock["minutes"], clock.get("seconds", 0),
            )
        except (KeyError, ValueError):
            return float("inf")
        now = dt_util.utcnow().astimezone(zone).replace(tzinfo=None)
        return abs((now - device).total_seconds())

    async def async_sync_clock(self) -> None:
        clock = (self.data or {}).get("clock") or await self.client.time()
        zone = self._zone(clock)
        now = dt_util.utcnow().astimezone(zone)
        await self.client.set_time(
            getattr(zone, "key", None) or clock.get("location", "UTC"),
            now.year, now.month - 1, now.day, now.hour, now.minute,
        )

    # -- writes --------------------------------------------------------
    async def async_set_channels(self, changes: dict[str, float]) -> None:
        """Set channels (percent). Manual control needs the schedule off."""
        levels = dict((self.data or {}).get("colors") or await self.client.colors())
        for key, pct in changes.items():
            if key not in levels:
                raise ValueError(f"unknown channel {key!r}")
            levels[key] = percent_to_raw(pct)
        if (self.data or {}).get("schedule_enabled", True):
            await self.client.set_schedule_enabled(False)
        await self.client.set_colors(levels)
        await self.async_request_refresh()

    async def async_set_schedule_enabled(self, enable: bool) -> None:
        await self.client.set_schedule_enabled(enable)
        await self.async_request_refresh()

    async def async_set_lunar(
        self, enable: bool | None = None, start: int | None = None, end: int | None = None
    ) -> None:
        """Change the moonlight window; unspecified fields keep their value."""
        cur = (self.data or {}).get("lunar")
        if cur is None:
            raise ValueError("this light does not report moonlight settings")
        enable = cur["enable"] if enable is None else enable
        start = cur["start"] if start is None else start
        end = cur["end"] if end is None else end
        for v in (start, end):
            if not 0 <= v < 1440:
                raise ValueError("moonlight times must be 00:00-23:59")
        await self.client.set_lunar(bool(enable), int(start), int(end))
        await self.async_request_refresh()

    async def async_set_schedule(self, schedule: dict) -> None:
        clean = validate_schedule(schedule, self.channels)
        await self.client.set_schedule(clean)
        self._schedule = None  # force a re-read
        await self.async_request_refresh()
