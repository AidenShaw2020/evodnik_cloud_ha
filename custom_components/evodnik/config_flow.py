from __future__ import annotations

from typing import Any, Dict, List, Optional

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult

from .const import (
    DOMAIN,
    CONF_USERNAME, CONF_PASSWORD, CONF_DEVICE_ID, CONF_DEVICE_NAME,
    CONF_SCAN_INTERVAL_MIN, DEFAULT_SCAN_INTERVAL_MIN,
    CONF_CONSUMPTION_UNIT, DEFAULT_CONSUMPTION_UNIT,
)
from .api import EvodnikClient


class EvodnikConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    def __init__(self) -> None:
        self._username: Optional[str] = None
        self._password: Optional[str] = None
        self._devices: List[Dict[str, Any]] = []

    async def async_step_user(self, user_input: Dict[str, Any] | None = None) -> FlowResult:
        errors: Dict[str, str] = {}
        if user_input is not None:
            self._username = user_input[CONF_USERNAME]
            self._password = user_input[CONF_PASSWORD]
            try:
                client = EvodnikClient()
                await self.hass.async_add_executor_job(client.login, self._username, self._password)
                self._devices = await self.hass.async_add_executor_job(client.get_device_list)
                if not self._devices:
                    errors["base"] = "no_devices"
                else:
                    return await self.async_step_select_device()
            except Exception:
                errors["base"] = "auth"

        schema = vol.Schema({
            vol.Required(CONF_USERNAME): str,
            vol.Required(CONF_PASSWORD): str,
        })
        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)

    async def async_step_select_device(self, user_input: Dict[str, Any] | None = None) -> FlowResult:
        errors: Dict[str, str] = {}
        device_map = {str(d["Value"]): d.get("Text") or str(d["Value"]) for d in self._devices}

        if user_input is not None:
            device_id = str(user_input[CONF_DEVICE_ID])
            name = device_map.get(device_id, f"Device {device_id}")
            await self.async_set_unique_id(f"{DOMAIN}_{self._username}_{device_id}")
            self._abort_if_unique_id_configured()
            self._sel_device_id = int(device_id)
            self._sel_device_name = name
            return await self.async_step_consumption_unit()

        schema = vol.Schema({
            vol.Required(CONF_DEVICE_ID): vol.In(device_map),
        })
        return self.async_show_form(step_id="select_device", data_schema=schema, errors=errors)

    async def async_step_consumption_unit(self, user_input: Dict[str, Any] | None = None) -> FlowResult:
        errors: Dict[str, str] = {}
        if user_input is not None:
            return self.async_create_entry(
                title=f"eVodník: {self._sel_device_name}",
                data={
                    CONF_USERNAME: self._username,
                    CONF_PASSWORD: self._password,
                    CONF_DEVICE_ID: int(self._sel_device_id),
                    CONF_DEVICE_NAME: self._sel_device_name,
                    CONF_CONSUMPTION_UNIT: user_input[CONF_CONSUMPTION_UNIT],
                },
                options={
                    CONF_SCAN_INTERVAL_MIN: DEFAULT_SCAN_INTERVAL_MIN,
                }
            )

        schema = vol.Schema({
            vol.Required(CONF_CONSUMPTION_UNIT, default=DEFAULT_CONSUMPTION_UNIT): str
        })
        return self.async_show_form(step_id="consumption_unit", data_schema=schema, errors=errors)

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: config_entries.ConfigEntry):
        return EvodnikOptionsFlow(config_entry)


class EvodnikOptionsFlow(config_entries.OptionsFlow):
    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        self.config_entry = config_entry

    async def async_step_init(self, user_input: Dict[str, Any] | None = None) -> FlowResult:
        return await self.async_step_options(user_input)

    async def async_step_options(self, user_input: Dict[str, Any] | None = None) -> FlowResult:
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        current = dict(self.config_entry.options)
        schema = vol.Schema({
            vol.Required(
                CONF_SCAN_INTERVAL_MIN,
                default=current.get(CONF_SCAN_INTERVAL_MIN, DEFAULT_SCAN_INTERVAL_MIN)
            ): vol.All(int, vol.Range(min=1, max=1440))
        })
        return self.async_show_form(step_id="options", data_schema=schema)

