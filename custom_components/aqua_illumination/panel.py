"""Serve the bundled Lovelace card and register it as a dashboard resource."""
from __future__ import annotations

import logging
from pathlib import Path

from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)

CARD_URL = "/aqua_illumination/aqua-illumination-card.js"
CARD_VERSION = "0.1.0"  # bump whenever the card JS changes (browser cache)
_KEY = "aqua_illumination_card_registered"


async def async_register_card(hass: HomeAssistant) -> None:
    if hass.data.get(_KEY):
        return
    source = Path(__file__).parent / "lovelace" / "aqua-illumination-card.js"
    if not source.is_file():
        _LOGGER.warning("Bundled card missing at %s", source)
        return
    try:
        from homeassistant.components.http import StaticPathConfig

        await hass.http.async_register_static_paths(
            [StaticPathConfig(CARD_URL, str(source), True)]
        )
    except RuntimeError:
        pass  # already registered (reload)
    hass.data[_KEY] = True

    from homeassistant.helpers.start import async_at_started

    async def _add(_event=None) -> None:
        if await _register_resource(hass):
            return
        try:
            from homeassistant.components import frontend

            frontend.add_extra_js_url(hass, f"{CARD_URL}?v={CARD_VERSION}")
        except Exception as err:  # noqa: BLE001
            _LOGGER.warning(
                "Could not auto-load the card (%s). Add %s?v=%s as a JavaScript "
                "module under Settings > Dashboards > Resources.",
                err, CARD_URL, CARD_VERSION,
            )

    async_at_started(hass, _add)


async def _register_resource(hass: HomeAssistant) -> bool:
    url = f"{CARD_URL}?v={CARD_VERSION}"
    try:
        lovelace = hass.data.get("lovelace")
        resources = getattr(lovelace, "resources", None)
        if resources is None and isinstance(lovelace, dict):
            resources = lovelace.get("resources")
        if resources is None or not hasattr(resources, "async_create_item"):
            return False
        if hasattr(resources, "loaded") and not resources.loaded:
            await resources.async_load()
            resources.loaded = True
        for item in resources.async_items():
            if str(item.get("url", "")).split("?")[0] == CARD_URL:
                if item.get("url") != url and item.get("id"):
                    await resources.async_update_item(item["id"], {"url": url})
                return True
        await resources.async_create_item({"res_type": "module", "url": url})
        return True
    except Exception as err:  # noqa: BLE001
        _LOGGER.debug("Lovelace resource registration failed: %s", err)
        return False
