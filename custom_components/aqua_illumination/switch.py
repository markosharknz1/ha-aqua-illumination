"""Schedule on/off, and a night-feeding look."""
from __future__ import annotations

from homeassistant.components.switch import SwitchEntity
from homeassistant.helpers.restore_state import RestoreEntity

from .const import DOMAIN
from .entity import AquaEntity

NIGHT_FEED_CHANNELS = ("deep_red", "red", "far_red")


async def async_setup_entry(hass, entry, async_add_entities):
    coord = hass.data[DOMAIN][entry.entry_id]
    ents = [ScheduleSwitch(coord), NightFeedSwitch(coord), NightLightSwitch(coord), LightsOffSwitch(coord), AllLightsSwitch(coord)]
    if (coord.data or {}).get("lunar") is not None:
        ents.append(MoonlightSwitch(coord))
    async_add_entities(ents)


class MoonlightSwitch(AquaEntity, SwitchEntity):
    """Lunar cycle: dims the schedule's night levels by moon phase (it adds no light itself)."""

    _attr_name = "Lunar cycle"
    _attr_icon = "mdi:moon-waning-crescent"

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "moonlight")

    @property
    def is_on(self) -> bool:
        return bool((self.coordinator.data.get("lunar") or {}).get("enable"))

    async def async_turn_on(self, **kwargs) -> None:
        await self.coordinator.async_set_lunar(enable=True)

    async def async_turn_off(self, **kwargs) -> None:
        await self.coordinator.async_set_lunar(enable=False)


class NightLightSwitch(AquaEntity, SwitchEntity):
    """Overlay a low glow on the chosen channels over a night window (the lunar
    mode then dims it by moon phase). Window/level/channels: aqua_illumination.set_night_light
    or the card."""

    _attr_name = "Night light"
    _attr_icon = "mdi:weather-night"

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "night_light")

    @property
    def is_on(self) -> bool:
        return bool(self.coordinator.night.get("enable"))

    @property
    def extra_state_attributes(self):
        n = self.coordinator.night
        return {k: n.get(k) for k in ("start", "end", "level", "channels")}

    async def async_turn_on(self, **kwargs) -> None:
        await self.coordinator.async_set_night(enable=True)

    async def async_turn_off(self, **kwargs) -> None:
        await self.coordinator.async_set_night(enable=False)


class AllLightsSwitch(AquaEntity, SwitchEntity):
    """All lights on / all lights off, the way automations (e.g. Feed and Water) expect.

    Off = every channel off until switched back on. On = the light goes back to
    exactly what it was doing (previous levels and schedule), so a feed routine
    that turns it off and later turns it on again restores the light rather than
    forcing it to full power. Same hold as "Lights off", with on meaning "lit"."""

    _attr_name = "All lights"
    _attr_icon = "mdi:lightbulb-group"

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "all_lights")

    @property
    def is_on(self) -> bool:
        return (self.coordinator.override or {}).get("reason") != "lights_off"

    async def async_turn_off(self, **kwargs) -> None:
        if self.is_on:
            await self.coordinator.async_override(None, None, "lights_off")

    async def async_turn_on(self, **kwargs) -> None:
        if not self.is_on:
            await self.coordinator.async_cancel_override()


class LightsOffSwitch(AquaEntity, SwitchEntity):
    """Lights off until switched back on (or for a set time via aqua_illumination.lights_off);
    the previous look and schedule come back afterwards."""

    _attr_name = "Lights off"
    _attr_icon = "mdi:lightbulb-off-outline"

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "lights_off")

    @property
    def is_on(self) -> bool:
        return (self.coordinator.override or {}).get("reason") == "lights_off"

    @property
    def extra_state_attributes(self):
        return {"until": (self.coordinator.override or {}).get("until")}

    async def async_turn_on(self, **kwargs) -> None:
        await self.coordinator.async_override(None, None, "lights_off")

    async def async_turn_off(self, **kwargs) -> None:
        await self.coordinator.async_cancel_override()


class ScheduleSwitch(AquaEntity, SwitchEntity):
    _attr_name = "Schedule"
    _attr_icon = "mdi:calendar-clock"

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "schedule_enabled")

    @property
    def is_on(self) -> bool:
        return bool(self.coordinator.data["schedule_enabled"])

    async def async_turn_on(self, **kwargs) -> None:
        await self.coordinator.async_set_schedule_enabled(True)

    async def async_turn_off(self, **kwargs) -> None:
        await self.coordinator.async_set_schedule_enabled(False)


class NightFeedSwitch(AquaEntity, SwitchEntity, RestoreEntity):
    """On = manual mode, everything off except the red channel(s).

    Off puts back exactly what was there (levels + schedule on/off), so the
    schedule resumes where it left off. The previous look is kept in the entity
    attributes, so it survives an HA restart.
    """

    _attr_name = "Night feeding"
    _attr_icon = "mdi:weather-night"

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "night_feeding")
        self._on = False
        self._prev: dict | None = None

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last = await self.async_get_last_state()
        if last and last.state == "on" and last.attributes.get("previous"):
            self._on = True
            self._prev = last.attributes["previous"]

    @property
    def is_on(self) -> bool:
        return self._on

    @property
    def extra_state_attributes(self):
        return {"previous": self._prev} if self._prev else {}

    async def async_turn_on(self, **kwargs) -> None:
        d = self.coordinator.data
        if not self._on:
            self._prev = {
                "colors": dict(d["colors"]),
                "schedule_enabled": d["schedule_enabled"],
            }
        co = self.coordinator
        reds = [c for c in co.night_feed_channels if c in d["colors"]] or [
            c for c in NIGHT_FEED_CHANNELS if c in d["colors"]]
        levels = {c: (co.night_feed_level if c in reds else 0) for c in d["colors"]}
        self._on = True
        await self.coordinator.async_set_channels(levels)
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs) -> None:
        prev, self._on = self._prev, False
        self._prev = None
        if prev:
            await self.coordinator.client.set_colors(dict(prev["colors"]))
            await self.coordinator.async_set_schedule_enabled(prev["schedule_enabled"])
        self.async_write_ha_state()
