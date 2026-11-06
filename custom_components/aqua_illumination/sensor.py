"""Temperature, schedule (for the card) and clock sensors."""
from __future__ import annotations

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorStateClass
from homeassistant.const import EntityCategory, UnitOfTemperature

from .const import DOMAIN
from homeassistant.util import dt as dt_util

from .entity import AquaEntity
from .moon import PHASES, moon_phase


async def async_setup_entry(hass, entry, async_add_entities):
    coord = hass.data[DOMAIN][entry.entry_id]
    ents = [TempSensor(coord), ScheduleSensor(coord), ClockSensor(coord), MoonSensor(coord)]
    if (coord.data or {}).get("stealth") is not None:
        ents.append(StealthSensor(coord))
    if coord.power_max:
        ents.append(PowerSensor(coord))
    async_add_entities(ents)


class TempSensor(AquaEntity, SensorEntity):
    _attr_name = "Temperature"
    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "temperature")

    @property
    def native_value(self):
        c = self.coordinator.data["temperature"].get("celsius")
        return None if c is None else round(c, 1)

    @property
    def extra_state_attributes(self):
        t = self.coordinator.data["temperature"]
        return {"fan": t.get("fan_status"), "thermal_shutdown": t.get("thermal_shutdown_status")}


class ScheduleSensor(AquaEntity, SensorEntity):
    """State = schedule name; attributes carry the ramps for the card."""

    _attr_name = "Schedule data"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:chart-line"

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "schedule_data")

    @property
    def native_value(self):
        return (self.coordinator.data.get("schedule") or {}).get("name")

    @property
    def extra_state_attributes(self):
        s = self.coordinator.data.get("schedule") or {}
        return {"ramps": s.get("ramps", []), "host": self.coordinator.client.host}


class ClockSensor(AquaEntity, SensorEntity):
    _attr_name = "Device clock"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:clock-outline"

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "clock")

    @property
    def native_value(self):
        c = self.coordinator.data["clock"]
        try:
            return (f"{c['year']:04d}-{c['month'] + 1:02d}-{c['day']:02d} "
                    f"{c['hours']:02d}:{c['minutes']:02d}")
        except (KeyError, TypeError):
            return None

    @property
    def extra_state_attributes(self):
        return {"location": self.coordinator.data["clock"].get("location")}


class MoonSensor(AquaEntity, SensorEntity):
    """Moon phase from the date. Lunar mode dims the schedule's night levels by
    this phase, so it explains how bright a "moonlit" night will be."""

    _attr_name = "Moon phase"
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = PHASES
    _attr_icon = "mdi:moon-waning-crescent"

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "moon_phase")

    @property
    def native_value(self):
        return moon_phase(dt_util.utcnow())["name"]

    @property
    def extra_state_attributes(self):
        m = moon_phase(dt_util.utcnow())
        lunar = self.coordinator.data.get("lunar") or {}
        return {
            "illumination": m["illumination"], "age_days": m["age_days"],
            "lunar_enabled": lunar.get("enable"),
            "lunar_start": lunar.get("start"), "lunar_end": lunar.get("end"),
        }


class PowerSensor(AquaEntity, SensorEntity):
    """Estimated draw: channel levels x the light's rated per-channel wattage."""

    _attr_name = "Power draw (estimated)"
    _attr_device_class = SensorDeviceClass.POWER
    _attr_native_unit_of_measurement = "W"
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "power_estimate")

    @property
    def native_value(self):
        return self.coordinator.power_estimate_w()


class StealthSensor(AquaEntity, SensorEntity):
    """The light's stealth settings (change them with aqua_illumination.set_stealth)."""

    _attr_name = "Stealth"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:eye-off-outline"

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "stealth")

    @property
    def native_value(self):
        st = self.coordinator.data.get("stealth") or {}
        return "enabled" if st.get("enable") else "disabled"

    @property
    def extra_state_attributes(self):
        st = self.coordinator.data.get("stealth") or {}
        return {
            "dim": st.get("dim"),
            "intensity": None if st.get("intensity") is None else round(st["intensity"] / 10, 1),
            "suspend_seconds": None if st.get("suspend") is None else st["suspend"] / 1000,
        }
