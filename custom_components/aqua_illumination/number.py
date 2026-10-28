"""One 0-100 % number per colour channel."""
from __future__ import annotations

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.const import PERCENTAGE

from .api import raw_to_percent
from .const import DOMAIN, channel_label
from .entity import AquaEntity


async def async_setup_entry(hass, entry, async_add_entities):
    coord = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(ChannelNumber(coord, ch) for ch in coord.channels)


class ChannelNumber(AquaEntity, NumberEntity):
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_native_min_value = 0
    _attr_native_max_value = 100
    _attr_native_step = 0.5
    _attr_mode = NumberMode.SLIDER
    _attr_icon = "mdi:brightness-percent"

    def __init__(self, coordinator, channel: str) -> None:
        super().__init__(coordinator, f"ch_{channel}")
        self._channel = channel
        self._attr_name = channel_label(channel)

    @property
    def native_value(self):
        raw = self.coordinator.data["colors"].get(self._channel)
        return None if raw is None else raw_to_percent(raw)

    async def async_set_native_value(self, value: float) -> None:
        await self.coordinator.async_set_channels({self._channel: value})
