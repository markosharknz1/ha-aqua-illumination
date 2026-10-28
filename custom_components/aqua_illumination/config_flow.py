"""Config + options flow: enter the light's IP, we confirm it by serial."""
from __future__ import annotations

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import AquaIlluminationClient, AquaIlluminationError
from .const import (
    CONF_AUTO_CLOCK,
    CONF_HOST,
    CONF_NAME,
    CONF_POLL_INTERVAL,
    DEFAULT_AUTO_CLOCK,
    DEFAULT_POLL_INTERVAL,
    DOMAIN,
)


class AquaConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input=None):
        errors = {}
        if user_input is not None:
            host = user_input[CONF_HOST].strip()
            client = AquaIlluminationClient(async_get_clientsession(self.hass), host)
            try:
                ident = await client.identity()
            except AquaIlluminationError:
                errors["base"] = "cannot_connect"
            else:
                if ident.get("parent"):
                    errors["base"] = "not_parent"
                else:
                    await self.async_set_unique_id(ident["serial_number"])
                    self._abort_if_unique_id_configured(updates={CONF_HOST: host})
                    title = user_input.get(CONF_NAME) or f"AI {ident.get('product', 'Prime')} {ident['serial_number'][-4:]}"
                    return self.async_create_entry(
                        title=title, data={CONF_HOST: host}
                    )
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({
                vol.Required(CONF_HOST): str,
                vol.Optional(CONF_NAME): str,
            }),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return AquaOptionsFlow()


class AquaOptionsFlow(config_entries.OptionsFlow):
    # Do not set self.config_entry: it is a read-only property on modern HA.
    async def async_step_init(self, user_input=None):
        if user_input is not None:
            return self.async_create_entry(data=user_input)
        o = self.config_entry.options
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema({
                vol.Optional(
                    CONF_POLL_INTERVAL,
                    default=o.get(CONF_POLL_INTERVAL, DEFAULT_POLL_INTERVAL),
                ): vol.All(int, vol.Range(min=10, max=600)),
                vol.Optional(
                    CONF_AUTO_CLOCK,
                    default=o.get(CONF_AUTO_CLOCK, DEFAULT_AUTO_CLOCK),
                ): bool,
            }),
        )
