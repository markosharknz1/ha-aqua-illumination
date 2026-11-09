"""Polling coordinator + the write helpers every entity shares."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from homeassistant.core import HomeAssistant
from homeassistant.helpers.event import async_track_point_in_utc_time, async_track_time_change
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
from .moon import moon_phase, night_glow_window
from .night import clean_night, compose, default_night, effective_night
from .presets import build_schedule, key_for_label, normalize

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
        # Schedule layers: what the user edits (day) + a night glow composed on top.
        self.day: dict | None = None
        self.night: dict = {}
        self._stored_night: dict = {}
        self._store_loaded = False
        self._written: dict | None = None  # normalised schedule we last put on the light
        # A temporary manual hold (lights off / preview); the previous look is restored after.
        self.override: dict | None = None
        self._override_unsub = None
        self._moon_window: dict | None = None  # tonight's glow window (follow the moon)
        self.moon_info: dict = {}
        self._moon_unsub = None
        self.night_feed_level: float = 25.0
        self.night_feed_channels: list[str] = []

    async def async_load_store(self) -> None:
        """Read the saved layers/presets/hold. Must run BEFORE the first refresh:
        the first poll saves, and saving before loading would wipe what was stored."""
        stored = await self._store.async_load() or {}
        self.saved_presets = stored.get("presets", {})
        self.day = stored.get("day")
        self._written = stored.get("written")
        self._stored_night = stored.get("night") or {}
        self.override = stored.get("override")
        self._store_loaded = True

    async def async_load_extras(self) -> None:
        """Night config (needs the channel list), re-arm a held timer, and the
        light's per-channel wattage (best effort). Runs after the first refresh."""
        try:
            self.night = clean_night(self._stored_night, self.channels)
        except ValueError:
            self.night = default_night(self.channels)
        if self.override:
            self._arm_override()
        self._moon_unsub = async_track_time_change(self.hass, self._moon_tick, hour=12, minute=0, second=0)
        if self.night.get("follow_moon"):
            try:
                await self.async_refresh_moon()
            except AquaIlluminationError as err:
                _LOGGER.warning("%s: follow-the-moon update failed (%s)", self.name, err)
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

    async def _async_save(self) -> None:
        if not self._store_loaded:  # never overwrite what has not been read yet
            _LOGGER.debug("%s: store not loaded yet; skipping save", self.name)
            return
        await self._store.async_save({
            "presets": self.saved_presets, "day": self.day, "night": self.night,
            "written": self._written, "override": self.override,
        })

    def day_schedule(self) -> dict | None:
        """The schedule as the user edits it (without the night glow)."""
        return self.day or (self.data or {}).get("schedule")

    def _reconcile(self, light: dict) -> bool:
        """Compare the light's schedule with what we last wrote. A difference means
        something else (the vendor app) changed it: adopt it as the new day layer.
        Returns True if our stored layers changed."""
        cur = normalize(light)
        if self.day is None or self._written is None:
            self.day, self._written = light, cur
            return True
        if cur != self._written:
            _LOGGER.warning(
                "%s: schedule changed outside Home Assistant; adopting it as the day layer",
                self.name,
            )
            self.day, self._written = light, cur
            return True
        return False

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
        sched = self.day_schedule() or await self.client.schedule()
        self.saved_presets[name] = {"name": name, "ramps": sched["ramps"]}
        await self._async_save()
        self.async_update_listeners()

    async def async_delete_preset(self, name: str) -> None:
        if self.saved_presets.pop(name, None) is None:
            raise ValueError(f"no saved preset {name!r}")
        await self._async_save()
        self.async_update_listeners()

    async def async_import_presets(self, data, replace: bool = False) -> int:
        from .presets import parse_import

        new = parse_import(data, self.channels, validate_schedule)
        clash = [n for n in new if n in self.saved_presets]
        if clash and not replace:
            raise ValueError(f"already saved: {', '.join(clash)} (set replace to overwrite)")
        self.saved_presets.update(new)
        await self._async_save()
        self.async_update_listeners()
        return len(new)

    async def async_apply_preset(self, name: str, night_glow: bool = False) -> None:
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
            fresh = None
            if self._schedule is None or self._polls % SCHEDULE_REFRESH_EVERY == 0:
                fresh = self._schedule = await self.client.schedule()
        except AquaIlluminationError as err:
            raise UpdateFailed(str(err)) from err
        self._polls += 1
        if fresh is not None and self._reconcile(fresh):
            await self._async_save()
        lunar = None
        try:
            lunar = await self.client.lunar()
        except AquaIlluminationError:
            pass  # firmware without moonlight support
        stealth = None
        try:
            stealth = await self.client.stealth()
        except AquaIlluminationError:
            pass  # firmware without stealth
        data = {
            "stealth": stealth, "colors": colors, "schedule_enabled": enabled,
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

    async def async_set_stealth(
        self, enable: bool | None = None, dim: bool | None = None,
        intensity: float | None = None, suspend: float | None = None,
    ) -> None:
        """Change stealth settings; unspecified fields keep their value.
        ``intensity`` is percent, ``suspend`` seconds."""
        cur = (self.data or {}).get("stealth")
        if cur is None:
            raise ValueError("this light does not report stealth settings")
        await self.client.set_stealth(
            cur["enable"] if enable is None else bool(enable),
            cur["dim"] if dim is None else bool(dim),
            cur["intensity"] if intensity is None else percent_to_raw(intensity),
            cur["suspend"] if suspend is None else int(round(suspend * 1000)),
        )
        await self.async_request_refresh()

    async def async_set_schedule(self, schedule: dict) -> None:
        """Write a schedule as the DAY layer; the night glow (if on) is composed on top."""
        self.day = validate_schedule(schedule, self.channels)
        await self._write_composed()

    async def _write_composed(self) -> None:
        day = self.day or validate_schedule(
            (self.data or {}).get("schedule") or await self.client.schedule(), self.channels)
        self.day = day
        composed = validate_schedule(compose(day, self._effective_night()), self.channels)
        await self.client.set_schedule(composed)
        self._written = normalize(composed)
        await self._async_save()
        self._schedule = None  # force a re-read
        await self.async_request_refresh()

    async def async_set_night(self, **changes) -> None:
        """Change the night-light layer; unspecified fields keep their value."""
        was_follow = bool(self.night.get("follow_moon"))
        self.night = clean_night(
            {**self.night, **{k: v for k, v in changes.items() if v is not None}},
            self.channels,
        )
        now_follow = bool(self.night["follow_moon"])
        if now_follow and not was_follow:
            await self._moon_takes_over_lunar()
        elif was_follow and not now_follow:
            await self._moon_releases_lunar()
        self._compute_moon()
        await self._write_composed()

    # -- follow the moon ------------------------------------------------
    def _effective_night(self) -> dict:
        return effective_night(self.night, self._moon_window)

    def _compute_moon(self) -> None:
        """Work out tonight's glow window (moon up inside the night hours) and the
        info the card shows. Pure maths; no I/O."""
        n = self.night
        if not n.get("follow_moon"):
            self._moon_window, self.moon_info = None, {}
            return
        zone = self._zone((self.data or {}).get("clock") or {})
        now = dt_util.utcnow().astimezone(zone)
        length = (int(n["end"]) - int(n["start"])) % 1440
        if length == 0:
            self._moon_window, self.moon_info = None, {"follow": True}
            return
        today_start = now.replace(hour=int(n["start"]) // 60, minute=int(n["start"]) % 60,
                                  second=0, microsecond=0)
        prev_start = today_start - timedelta(days=1)
        # A night still in progress counts as "tonight"; otherwise the coming one.
        start_dt = prev_start if now < prev_start + timedelta(minutes=length) else today_start
        found = night_glow_window(
            start_dt, length / 60, self.hass.config.latitude, self.hass.config.longitude)
        if found is None:
            self._moon_window = None
            mid = moon_phase(start_dt + timedelta(minutes=length / 2))
            self.moon_info = {
                "follow": True, "phase": mid["name"], "illumination": mid["illumination"],
                "window": None, "level_effective": 0,
            }
            return
        def minute(dt, up):
            dt = dt.astimezone(zone)
            m = dt.hour * 60 + dt.minute + (1 if up and dt.second >= 30 else 0)
            return m % 1440
        s_m, e_m = minute(found["start"], True), minute(found["end"], False)
        if s_m == e_m:
            self._moon_window = None
            self.moon_info = {"follow": True, "window": None, "level_effective": 0}
            return
        self._moon_window = {"start": s_m, "end": e_m, "illumination": found["illumination"]}
        eff = effective_night(n, self._moon_window)
        self.moon_info = {
            "follow": True, "phase": moon_phase(found["start"])["name"],
            "illumination": found["illumination"], "window": [s_m, e_m],
            "level_effective": eff["level"], "night_start": start_dt.isoformat(),
        }

    async def async_refresh_moon(self) -> None:
        """Recompute tonight's window and rewrite the schedule only if it changed."""
        self._compute_moon()
        if not self.night.get("follow_moon") or self.day is None:
            return
        composed = validate_schedule(compose(self.day, self._effective_night()), self.channels)
        if normalize(composed) != self._written:
            await self._write_composed()
        else:
            self.async_update_listeners()

    async def _moon_tick(self, _now) -> None:
        try:
            await self.async_refresh_moon()
        except (AquaIlluminationError, ValueError) as err:
            _LOGGER.warning("%s: follow-the-moon update failed (%s)", self.name, err)

    async def _moon_takes_over_lunar(self) -> None:
        """We scale the glow by the moon's phase ourselves, so the light's own lunar
        mode would dim it a second time. Switch it off (remembering) while following."""
        lunar = (self.data or {}).get("lunar")
        if lunar and lunar.get("enable"):
            await self.client.set_lunar(False, int(lunar["start"]), int(lunar["end"]))
            self.night["lunar_restore"] = True

    async def _moon_releases_lunar(self) -> None:
        if self.night.pop("lunar_restore", False):
            lunar = (self.data or {}).get("lunar") or {"start": 1200, "end": 240}
            await self.client.set_lunar(True, int(lunar["start"]), int(lunar["end"]))

    # -- temporary overrides (lights off / preview) --------------------
    async def async_override(
        self, levels: dict[str, float] | None, minutes: float | None, reason: str
    ) -> None:
        """Hold manual levels (``None`` = everything off) for ``minutes`` (``None`` =
        until cancelled); the previous colours and schedule on/off are restored after."""
        d = self.data or {}
        if self.override is None:
            self.override = {
                "colors": dict(d.get("colors") or {}),
                "schedule_enabled": d.get("schedule_enabled", True),
            }
        until = None if minutes is None else dt_util.utcnow() + timedelta(minutes=minutes)
        self.override.update(until=until.isoformat() if until else None, reason=reason)
        full = {c: 0 for c in self.channels}
        full.update(levels or {})
        await self.async_set_channels(full)
        await self._async_save()
        self._arm_override()
        self.async_update_listeners()

    async def async_cancel_override(self) -> None:
        if self.override is None:
            return
        prev = self.override
        self._cancel_override_timer()
        await self.client.set_colors(dict(prev["colors"]))
        await self.client.set_schedule_enabled(bool(prev["schedule_enabled"]))
        self.override = None
        await self._async_save()
        await self.async_request_refresh()

    def _cancel_override_timer(self) -> None:
        if self._override_unsub:
            self._override_unsub()
            self._override_unsub = None

    def _arm_override(self, retry_seconds: float | None = None) -> None:
        self._cancel_override_timer()
        until = (self.override or {}).get("until")
        if not until:
            return
        when = dt_util.parse_datetime(until)
        if when is None:
            return
        if retry_seconds is not None:
            when = dt_util.utcnow() + timedelta(seconds=retry_seconds)

        async def _expire(_now) -> None:
            self._override_unsub = None
            try:
                await self.async_cancel_override()
            except AquaIlluminationError as err:
                _LOGGER.warning("%s: could not restore after hold (%s); retrying", self.name, err)
                self._arm_override(retry_seconds=60)

        self._override_unsub = async_track_point_in_utc_time(self.hass, _expire, when)

    async def async_shutdown(self) -> None:
        self._cancel_override_timer()
        if self._moon_unsub:
            self._moon_unsub()
            self._moon_unsub = None
        await super().async_shutdown()
