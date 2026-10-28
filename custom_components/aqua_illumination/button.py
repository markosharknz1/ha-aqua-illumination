"""Sync clock / refresh buttons."""
from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.const import EntityCategory

from .const import DOMAIN
from .entity import AquaEntity


async def async_setup_entry(hass, entry, async_add_entities):
    coord = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([SyncClockButton(coord), RefreshButton(coord)])


class SyncClockButton(AquaEntity, ButtonEntity):
    _attr_name = "Sync clock"
    _attr_icon = "mdi:clock-check-outline"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "sync_clock")

    async def async_press(self) -> None:
        await self.coordinator.async_sync_clock()
        await self.coordinator.async_request_refresh()


class RefreshButton(AquaEntity, ButtonEntity):
    _attr_name = "Refresh"
    _attr_icon = "mdi:refresh"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "refresh")

    async def async_press(self) -> None:
        self.coordinator._schedule = None
        await self.coordinator.async_request_refresh()
