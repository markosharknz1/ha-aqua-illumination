"""Connection sensor: is the light reachable, and its dropout history."""
from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.const import EntityCategory

from .const import DOMAIN
from .entity import AquaEntity


async def async_setup_entry(hass, entry, async_add_entities):
    async_add_entities([ConnectionSensor(hass.data[DOMAIN][entry.entry_id])])


class ConnectionSensor(AquaEntity, BinarySensorEntity):
    """On = answering polls. Stays available while the light is down so the
    card (and automations) can see the outage instead of a blank."""

    _attr_name = "Connection"
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "connection")

    @property
    def available(self) -> bool:
        return True

    @property
    def is_on(self) -> bool:
        return self.coordinator.dropout.online

    @property
    def extra_state_attributes(self):
        d = self.coordinator.dropout
        iso = lambda t: t.isoformat() if t else None
        return {
            "last_seen": iso(d.last_seen),
            "offline_since": iso(d.offline_since),
            "dropouts": d.dropouts,
            "last_outage_seconds": d.last_outage_seconds,
            "last_error": d.last_error,
            "host": self.coordinator.client.host,
        }
