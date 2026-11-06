"""Diagnostics download (Settings > Devices & services > the light > Download diagnostics)."""
from __future__ import annotations

from homeassistant.components.diagnostics import async_redact_data

from .const import DOMAIN

TO_REDACT = {"host", "serial", "serial_number", "configuration_url", "title"}


async def async_get_config_entry_diagnostics(hass, entry) -> dict:
    coord = hass.data[DOMAIN][entry.entry_id]
    d = coord.dropout
    iso = lambda t: t.isoformat() if t else None  # noqa: E731
    return async_redact_data({
        "entry": {"title": entry.title, "data": dict(entry.data), "options": dict(entry.options)},
        "identity": coord.identity,
        "data": coord.data,
        "day_schedule": coord.day,
        "night": coord.night,
        "override": coord.override,
        "saved_presets": sorted(coord.saved_presets),
        "power_rated_mw": coord.power_max,
        "connection": {
            "online": d.online, "dropouts": d.dropouts, "failures": d.failures,
            "last_seen": iso(d.last_seen), "offline_since": iso(d.offline_since),
            "last_error": d.last_error,
        },
    }, TO_REDACT)
