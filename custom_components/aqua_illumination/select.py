"""Schedule preset picker: built-in looks plus presets saved from the light."""
from __future__ import annotations

from homeassistant.components.select import SelectEntity

from .const import DOMAIN
from .entity import AquaEntity


async def async_setup_entry(hass, entry, async_add_entities):
    async_add_entities([PresetSelect(hass.data[DOMAIN][entry.entry_id])])


class PresetSelect(AquaEntity, SelectEntity):
    """Picking an option rewrites the light's schedule. The light does not
    report which preset is loaded, so the entity remembers the last one applied
    here and shows it only while the schedule's name still matches."""

    _attr_name = "Schedule preset"
    _attr_icon = "mdi:playlist-star"

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "preset")

    @property
    def options(self) -> list[str]:
        return self.coordinator.preset_options

    @property
    def current_option(self) -> str | None:
        name = (self.coordinator.data.get("schedule") or {}).get("name")
        return name if name in self.options else None

    async def async_select_option(self, option: str) -> None:
        await self.coordinator.async_apply_preset(option)
