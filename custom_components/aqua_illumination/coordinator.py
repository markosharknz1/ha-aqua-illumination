"""Polling coordinator + the write helpers every entity shares."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store
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
    OFFLINE_AFTER_FAILURES,
    SCHEDULE_REFRESH_EVERY,
)
from .dropout import DropoutTracker
from .presets import build_schedule, key_for_label

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
        self.dropout = DropoutTracker(OFFLINE_AFTER_FAILURES)
        self._announced = False  # a dropout notification is outstanding
        self._store = Store(hass, 1, f"{DOMAIN}.presets.{self.serial}")
        self.saved_presets: dict[str, dict] = {}
        self.power_max: dict[str, float] = {}  # channel -> mW at 100 %

    async def async_load_extras(self) -> None:
        """Saved presets + the light's per-channel wattage (both best effort)."""
        stored = await self._store.async_load()
        self.saved_presets = (stored or {}).get("presets", {})
        try:
            power = await self.client.power()
        except AquaIlluminationError:
            return
        devs = power.get("devices") or []
        dev = next((d for d in devs if d.get("serial_number") == self.serial), None)
        dev = dev or (devs[0] if devs else None)
        norm = (dev or {}).get("normal")
        if isinstance(norm, dict):
            self.power_max = {k: float(v) for k, v in norm.items()
                              if isinstance(v, (int, float))}

    def power_estimate_w(self) -> float | None:
        """Estimated draw from channel levels x rated per-channel wattage."""
        colors = (self.data or {}).get("colors")
        if not self.power_max or not colors:
            return None
        mw = sum(self.power_max.get(c, 0) * min(v, 1000) / 1000 for c, v in colors.items())
        return round(mw / 1000, 1)

    @property
    def preset_options(self) -> list[str]:
        from .presets import builtin_names
        return builtin_names() + sorted(self.saved_presets)

    async def async_save_preset(self, name: str) -> None:
        name = name.strip()
        if not name or key_for_label(name):
            raise ValueError("pick a name that is not a built-in preset")
        sched = await self.client.schedule()
        self.saved_presets[name] = {"name": name, "ramps": sched["ramps"]}
        await self._store.async_save({"presets": self.saved_presets})
        self.async_update_listeners()

    async def async_delete_preset(self, name: str) -> None:
        if self.saved_presets.pop(name, None) is None:
            raise ValueError(f"no saved preset {name!r}")
        await self._store.async_save({"presets": self.saved_presets})
        self.async_update_listeners()

    async def async_apply_preset(self, name: str, night_glow: bool = True) -> None:
        key = key_for_label(name)
        if key:
            schedule = build_schedule(key, self.channels, night_glow)
        elif name in self.saved_presets:
            schedule = self.saved_presets[name]
        else:
            raise ValueError(f"unknown preset {name!r}")
        await self.async_set_schedule(schedule)

    @property
    def channels(self) -> list[str]:
        return list((self.data or {}).get("colors", {}))

    async def _async_update_data(self) -> dict:
        try:
            data = await self._poll()
        except UpdateFailed as err:
            was_online = self.dropout.online
            offline = self.dropout.failure(dt_util.utcnow(), str(err))
            if not offline and self.data:
                # A single missed poll is a blip: keep the last good state
                # rather than flapping every entity to unavailable.
                _LOGGER.debug("Poll failed (%s); keeping last state", err)
                return self.data
            if was_online and offline and self.dropout.last_seen is not None:
                # Only a light that was working counts: no alarm for a light
                # that never answered since HA started.
                self._announce(offline=True)
            raise
        if self.dropout.success(dt_util.utcnow()) and self._announced:
            self._announce(offline=False)
        return data

    def _announce(self, *, offline: bool) -> None:
        """Fire an event and raise/clear a persistent notification, so a drop is
        actively surfaced rather than only logged. The light keeps running its
        stored schedule; only our control and telemetry are lost."""
        from homeassistant.components import persistent_notification

        label = self.identity.get("name") or f"AI Prime {self.serial[-4:]}"
        notif_id = f"{DOMAIN}_dropout_{self.serial}"
        payload = {"serial": self.serial, "name": label, "host": self.client.host}
        self._announced = offline
        if offline:
            _LOGGER.warning("%s went offline: %s", label, self.dropout.last_error)
            self.hass.bus.async_fire(f"{DOMAIN}_dropout", payload)
            persistent_notification.async_create(
                self.hass,
                f"{label} has dropped off the network - control and status are "
                "lost (the light keeps running its stored schedule). Check its "
                "power and WiFi.",
                title="Aqua Illumination light offline",
                notification_id=notif_id,
            )
        else:
            _LOGGER.info(
                "%s is back online after %.0f s", label,
                self.dropout.last_outage_seconds or 0,
            )
            self.hass.bus.async_fire(f"{DOMAIN}_reconnected", payload)
            persistent_notification.async_dismiss(self.hass, notif_id)

    async def _poll(self) -> dict:
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
