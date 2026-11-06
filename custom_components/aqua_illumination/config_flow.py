"""Config + options flow: enter the light's IP, we confirm it by serial."""
from __future__ import annotations

import voluptuous as vol
from homeassistant.helpers import config_validation as cv
from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import AquaIlluminationClient, AquaIlluminationError
from .discovery import adapter_networks, hosts_from_cidr, scan
from .const import (
    CONF_AUTO_CLOCK,
    CONF_HOST,
    CONF_NAME,
    CONF_NIGHT_FEED_CHANNELS,
    CONF_NIGHT_FEED_LEVEL,
    CONF_POLL_INTERVAL,
    DEFAULT_AUTO_CLOCK,
    DEFAULT_NIGHT_FEED_LEVEL,
    DEFAULT_POLL_INTERVAL,
    DOMAIN,
    channel_label,
)


class AquaConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input=None):
        return self.async_show_menu(step_id="user", menu_options=["manual", "search"])

    async def async_step_search(self, user_input=None):
        """Scan the local network for lights (the light's own address may change)."""
        errors = {}
        if user_input is not None:
            try:
                hosts = []
                for cidr in (user_input.get("networks") or "").replace(",", " ").split():
                    hosts += hosts_from_cidr(cidr)
                if not hosts:
                    from homeassistant.components import network

                    nets = adapter_networks(await network.async_get_adapters(self.hass))
                    for cidr in nets:
                        hosts += hosts_from_cidr(cidr)
            except ValueError:
                errors["networks"] = "bad_network"
            else:
                known = self._async_current_ids()
                found = await scan(async_get_clientsession(self.hass), sorted(set(hosts)))
                self._found = {
                    host: ident for host, ident in found
                    if not ident.get("parent") and ident["serial_number"] not in known
                }
                if self._found:
                    return await self.async_step_pick()
                errors["base"] = "none_found"
        return self.async_show_form(
            step_id="search",
            data_schema=vol.Schema({vol.Optional("networks", default=""): str}),
            errors=errors,
        )

    async def async_step_pick(self, user_input=None):
        if user_input is not None:
            host = user_input[CONF_HOST]
            ident = self._found[host]
            await self.async_set_unique_id(ident["serial_number"])
            self._abort_if_unique_id_configured(updates={CONF_HOST: host})
            return self.async_create_entry(title=self._title(ident), data={CONF_HOST: host})
        return self.async_show_form(
            step_id="pick",
            data_schema=vol.Schema({vol.Required(CONF_HOST): vol.In({
                host: f"{self._title(ident)} ({host})" for host, ident in self._found.items()
            })}),
        )

    async def async_step_manual(self, user_input=None):
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
            step_id="manual",
            data_schema=vol.Schema({
                vol.Required(CONF_HOST): str,
                vol.Optional(CONF_NAME): str,
            }),
            errors=errors,
        )

    async def async_step_dhcp(self, discovery_info):
        """The light (matched by MAC prefix) appeared on the network. If it is
        already set up under another address this just updates the host, so a
        DHCP change never leaves the integration pointing at a dead IP."""
        host = discovery_info.ip
        client = AquaIlluminationClient(async_get_clientsession(self.hass), host)
        try:
            ident = await client.identity()
        except AquaIlluminationError:
            return self.async_abort(reason="cannot_connect")
        if ident.get("parent"):
            return self.async_abort(reason="not_parent")
        await self.async_set_unique_id(ident["serial_number"])
        self._abort_if_unique_id_configured(updates={CONF_HOST: host})
        self._discovered = (host, ident)
        self.context["title_placeholders"] = {"name": self._title(ident)}
        return await self.async_step_confirm()

    @staticmethod
    def _title(ident) -> str:
        return f"AI {ident.get('product', 'Prime')} {ident['serial_number'][-4:]}"

    async def async_step_confirm(self, user_input=None):
        host, ident = self._discovered
        if user_input is not None:
            return self.async_create_entry(title=self._title(ident), data={CONF_HOST: host})
        self._set_confirm_only()
        return self.async_show_form(
            step_id="confirm",
            description_placeholders={"name": self._title(ident), "host": host},
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
        coord = self.hass.data.get(DOMAIN, {}).get(self.config_entry.entry_id)
        channels = coord.channels if coord else []
        extra = {}
        if channels:
            extra[vol.Optional(
                CONF_NIGHT_FEED_CHANNELS, default=o.get(CONF_NIGHT_FEED_CHANNELS, []),
            )] = cv.multi_select({c: channel_label(c) for c in channels})
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema({
                vol.Optional(
                    CONF_NIGHT_FEED_LEVEL,
                    default=o.get(CONF_NIGHT_FEED_LEVEL, DEFAULT_NIGHT_FEED_LEVEL),
                ): vol.All(vol.Coerce(float), vol.Range(min=0, max=100)),
                **extra,
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
