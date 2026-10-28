"""Services: set_channels, set_schedule, sync_clock.

Each takes ``entity_id`` - any entity that belongs to the light.
"""
from __future__ import annotations

import voluptuous as vol
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import entity_registry as er

from .api import AquaIlluminationError
from .const import DOMAIN, SERVICE_SET_SCHEDULE, SERVICE_SYNC_CLOCK

SERVICE_SET_CHANNELS = "set_channels"

_BASE = {vol.Required("entity_id"): cv.entity_id}

SET_CHANNELS = vol.Schema({
    **_BASE,
    vol.Required("levels"): {cv.string: vol.All(vol.Coerce(float), vol.Range(min=0, max=100))},
})
SET_SCHEDULE = vol.Schema({
    **_BASE,
    vol.Required("ramps"): [{
        vol.Required("color"): cv.string,
        vol.Required("points"): [{
            vol.Required("time"): vol.All(int, vol.Range(min=0, max=1440)),
            vol.Required("intensity"): vol.All(int, vol.Range(min=0, max=1000)),
        }],
    }],
    vol.Optional("name", default="default"): cv.string,
})
SYNC_CLOCK = vol.Schema(_BASE)
SET_LUNAR = vol.Schema({
    **_BASE,
    vol.Optional("enable"): cv.boolean,
    vol.Optional("start"): cv.time,
    vol.Optional("end"): cv.time,
})


def _coordinator(hass: HomeAssistant, entity_id: str):
    ent = er.async_get(hass).async_get(entity_id)
    coord = hass.data.get(DOMAIN, {}).get(ent.config_entry_id) if ent else None
    if coord is None:
        raise HomeAssistantError(f"{entity_id} does not belong to an Aqua Illumination light")
    return coord


def async_register_services(hass: HomeAssistant) -> None:
    if hass.services.has_service(DOMAIN, SERVICE_SYNC_CLOCK):
        return

    async def _run(call: ServiceCall, fn):
        coord = _coordinator(hass, call.data["entity_id"])
        try:
            await fn(coord, call.data)
        except (AquaIlluminationError, ValueError) as err:
            raise HomeAssistantError(str(err)) from err

    async def set_channels(call: ServiceCall) -> None:
        await _run(call, lambda c, d: c.async_set_channels(d["levels"]))

    async def set_schedule(call: ServiceCall) -> None:
        await _run(call, lambda c, d: c.async_set_schedule(
            {"name": d["name"], "ramps": d["ramps"]}))

    async def sync_clock(call: ServiceCall) -> None:
        async def go(c, _d):
            await c.async_sync_clock()
            await c.async_request_refresh()
        await _run(call, go)

    async def set_lunar(call: ServiceCall) -> None:
        def mins(t):
            return None if t is None else t.hour * 60 + t.minute
        await _run(call, lambda c, d: c.async_set_lunar(
            d.get("enable"), mins(d.get("start")), mins(d.get("end"))))

    hass.services.async_register(DOMAIN, "set_lunar", set_lunar, SET_LUNAR)
    hass.services.async_register(DOMAIN, SERVICE_SET_CHANNELS, set_channels, SET_CHANNELS)
    hass.services.async_register(DOMAIN, SERVICE_SET_SCHEDULE, set_schedule, SET_SCHEDULE)
    hass.services.async_register(DOMAIN, SERVICE_SYNC_CLOCK, sync_clock, SYNC_CLOCK)
