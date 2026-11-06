"""Services: set_channels, set_schedule, sync_clock.

Each takes ``entity_id`` - any entity that belongs to the light.
"""
from __future__ import annotations

import voluptuous as vol
from homeassistant.core import HomeAssistant, ServiceCall, SupportsResponse
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import entity_registry as er

from .api import AquaIlluminationError
from .const import DOMAIN, SERVICE_SET_SCHEDULE, SERVICE_SYNC_CLOCK

SERVICE_SET_CHANNELS = "set_channels"

_BASE = {vol.Required("entity_id"): cv.entity_ids}  # one entity or a list: several lights

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


SET_PRESET = vol.Schema({
    **_BASE,
    vol.Required("preset"): cv.string,
    vol.Optional("night_glow", default=True): cv.boolean,
})
SAVE_PRESET = vol.Schema({**_BASE, vol.Required("name"): cv.string})
DELETE_PRESET = SAVE_PRESET
SET_STEALTH = vol.Schema({
    **_BASE,
    vol.Optional("enable"): cv.boolean,
    vol.Optional("dim"): cv.boolean,
    vol.Optional("intensity"): vol.All(vol.Coerce(float), vol.Range(min=0, max=100)),
    vol.Optional("suspend"): vol.All(vol.Coerce(float), vol.Range(min=0, max=3600)),
})
SET_NIGHT = vol.Schema({
    **_BASE,
    vol.Optional("enable"): cv.boolean,
    vol.Optional("start"): cv.time,
    vol.Optional("end"): cv.time,
    vol.Optional("level"): vol.All(vol.Coerce(float), vol.Range(min=0, max=100)),
    vol.Optional("channels"): vol.All(cv.ensure_list, [cv.string]),
})
LIGHTS_OFF = vol.Schema({
    **_BASE,
    vol.Optional("duration"): vol.All(vol.Coerce(float), vol.Range(min=0.5, max=1440)),
})
PREVIEW = vol.Schema({
    **_BASE,
    vol.Required("levels"): {cv.string: vol.All(vol.Coerce(float), vol.Range(min=0, max=100))},
    vol.Optional("duration", default=10): vol.All(vol.Coerce(float), vol.Range(min=0.5, max=120)),
})
EXPORT_PRESETS = vol.Schema({vol.Required("entity_id"): cv.entity_id})
IMPORT_PRESETS = vol.Schema({
    **_BASE,
    vol.Required("data"): vol.Any(cv.string, dict),
    vol.Optional("replace", default=False): cv.boolean,
})
COPY_SCHEDULE = vol.Schema({
    vol.Required("source"): cv.entity_id,
    vol.Required("entity_id"): cv.entity_ids,
})


def _coordinator(hass: HomeAssistant, entity_id: str):
    ent = er.async_get(hass).async_get(entity_id)
    coord = hass.data.get(DOMAIN, {}).get(ent.config_entry_id) if ent else None
    if coord is None:
        raise HomeAssistantError(f"{entity_id} does not belong to an Aqua Illumination light")
    return coord


def _coordinators(hass: HomeAssistant, entity_ids) -> list:
    """Resolve entity ids to their lights, one coordinator per light."""
    seen, out = set(), []
    for eid in entity_ids:
        c = _coordinator(hass, eid)
        if c.serial not in seen:
            seen.add(c.serial)
            out.append(c)
    return out


def async_register_services(hass: HomeAssistant) -> None:
    if hass.services.has_service(DOMAIN, SERVICE_SYNC_CLOCK):
        return

    async def _run(call: ServiceCall, fn):
        # Every light is tried even if one is down; failures are reported together.
        errors = []
        for coord in _coordinators(hass, call.data["entity_id"]):
            try:
                await fn(coord, call.data)
            except (AquaIlluminationError, ValueError) as err:
                errors.append(f"{coord.serial[-4:]}: {err}")
        if errors:
            raise HomeAssistantError("; ".join(errors))

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

    async def apply_preset(call: ServiceCall) -> None:
        await _run(call, lambda c, d: c.async_apply_preset(d["preset"], d["night_glow"]))

    async def save_preset(call: ServiceCall) -> None:
        await _run(call, lambda c, d: c.async_save_preset(d["name"]))

    async def delete_preset(call: ServiceCall) -> None:
        await _run(call, lambda c, d: c.async_delete_preset(d["name"]))

    async def copy_schedule(call: ServiceCall) -> None:
        src = _coordinator(hass, call.data["source"])
        try:
            sched = src.day_schedule() or await src.client.schedule()
        except AquaIlluminationError as err:
            raise HomeAssistantError(f"source light: {err}") from err
        await _run(call, lambda c, _d: c.async_set_schedule(sched))

    async def set_stealth(call: ServiceCall) -> None:
        await _run(call, lambda c, d: c.async_set_stealth(
            d.get("enable"), d.get("dim"), d.get("intensity"), d.get("suspend")))

    async def set_night_light(call: ServiceCall) -> None:
        def mins(t):
            return None if t is None else t.hour * 60 + t.minute
        await _run(call, lambda c, d: c.async_set_night(
            enable=d.get("enable"), start=mins(d.get("start")), end=mins(d.get("end")),
            level=d.get("level"), channels=d.get("channels")))

    async def lights_off(call: ServiceCall) -> None:
        await _run(call, lambda c, d: c.async_override(None, d.get("duration"), "lights_off"))

    async def cancel_lights_off(call: ServiceCall) -> None:
        await _run(call, lambda c, _d: c.async_cancel_override())

    async def preview_levels(call: ServiceCall) -> None:
        await _run(call, lambda c, d: c.async_override(d["levels"], d["duration"], "preview"))

    async def export_presets(call: ServiceCall) -> dict:
        from .presets import export_payload
        return export_payload(_coordinator(hass, call.data["entity_id"]).saved_presets)

    async def import_presets(call: ServiceCall) -> None:
        await _run(call, lambda c, d: c.async_import_presets(d["data"], d["replace"]))

    hass.services.async_register(DOMAIN, "set_night_light", set_night_light, SET_NIGHT)
    hass.services.async_register(DOMAIN, "lights_off", lights_off, LIGHTS_OFF)
    hass.services.async_register(DOMAIN, "cancel_lights_off", cancel_lights_off, SYNC_CLOCK)
    hass.services.async_register(DOMAIN, "preview_levels", preview_levels, PREVIEW)
    hass.services.async_register(
        DOMAIN, "export_presets", export_presets, EXPORT_PRESETS,
        supports_response=SupportsResponse.ONLY)
    hass.services.async_register(DOMAIN, "import_presets", import_presets, IMPORT_PRESETS)
    hass.services.async_register(DOMAIN, "set_stealth", set_stealth, SET_STEALTH)
    hass.services.async_register(DOMAIN, "apply_preset", apply_preset, SET_PRESET)
    hass.services.async_register(DOMAIN, "save_preset", save_preset, SAVE_PRESET)
    hass.services.async_register(DOMAIN, "delete_preset", delete_preset, DELETE_PRESET)
    hass.services.async_register(DOMAIN, "copy_schedule", copy_schedule, COPY_SCHEDULE)
    hass.services.async_register(DOMAIN, "set_lunar", set_lunar, SET_LUNAR)
    hass.services.async_register(DOMAIN, SERVICE_SET_CHANNELS, set_channels, SET_CHANNELS)
    hass.services.async_register(DOMAIN, SERVICE_SET_SCHEDULE, set_schedule, SET_SCHEDULE)
    hass.services.async_register(DOMAIN, SERVICE_SYNC_CLOCK, sync_clock, SYNC_CLOCK)
