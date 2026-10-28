"""Moonlight start / end time."""
from __future__ import annotations

from datetime import time

from homeassistant.components.time import TimeEntity

from .const import DOMAIN
from .entity import AquaEntity


async def async_setup_entry(hass, entry, async_add_entities):
    coord = hass.data[DOMAIN][entry.entry_id]
    if (coord.data or {}).get("lunar") is None:
        return
    async_add_entities([MoonTime(coord, "start"), MoonTime(coord, "end")])


class MoonTime(AquaEntity, TimeEntity):
    _attr_icon = "mdi:moon-waning-crescent"

    def __init__(self, coordinator, which: str) -> None:
        super().__init__(coordinator, f"moonlight_{which}")
        self._which = which
        self._attr_name = f"Lunar {which}"

    @property
    def native_value(self) -> time | None:
        m = (self.coordinator.data.get("lunar") or {}).get(self._which)
        return None if m is None else time(m // 60 % 24, m % 60)

    async def async_set_value(self, value: time) -> None:
        await self.coordinator.async_set_lunar(
            **{self._which: value.hour * 60 + value.minute}
        )
