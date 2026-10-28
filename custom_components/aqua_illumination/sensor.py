"""Temperature, schedule (for the card) and clock sensors."""
from __future__ import annotations

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorStateClass
from homeassistant.const import EntityCategory, UnitOfTemperature

from .const import DOMAIN
from .entity import AquaEntity


async def async_setup_entry(hass, entry, async_add_entities):
    coord = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([TempSensor(coord), ScheduleSensor(coord), ClockSensor(coord)])


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
