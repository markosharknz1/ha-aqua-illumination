"""Aqua Illumination Prime lights for Home Assistant (local, cloud-free)."""
from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import AquaIlluminationClient, AquaIlluminationError
from .const import (
    CONF_AUTO_CLOCK,
    CONF_HOST,
    CONF_POLL_INTERVAL,
    DEFAULT_AUTO_CLOCK,
    DEFAULT_POLL_INTERVAL,
    DOMAIN,
)
from .coordinator import AquaCoordinator

PLATFORMS = ["number", "switch", "sensor", "button", "time"]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    client = AquaIlluminationClient(async_get_clientsession(hass), entry.data[CONF_HOST])
    try:
        identity = await client.identity()
    except AquaIlluminationError as err:
        raise ConfigEntryNotReady(str(err)) from err

    coordinator = AquaCoordinator(
        hass, client, identity,
        entry.options.get(CONF_POLL_INTERVAL, DEFAULT_POLL_INTERVAL),
        entry.options.get(CONF_AUTO_CLOCK, DEFAULT_AUTO_CLOCK),
    )
    await coordinator.async_config_entry_first_refresh()
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator

    entry.async_on_unload(entry.add_update_listener(_async_reload))
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    from .panel import async_register_card
    from .services import async_register_services

    async_register_services(hass)
    await async_register_card(hass)
    return True


async def _async_reload(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if ok:
        hass.data[DOMAIN].pop(entry.entry_id, None)
    return ok
