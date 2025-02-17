"""Config flow for Homewizard."""
from __future__ import annotations

import logging
from typing import Any

import aiohwenergy
from aiohwenergy.hwenergy import SUPPORTED_DEVICES
import async_timeout
from voluptuous import Required, Schema

from homeassistant import config_entries
from homeassistant.components import zeroconf
from homeassistant.const import CONF_IP_ADDRESS
from homeassistant.data_entry_flow import AbortFlow, FlowResult

from .const import CONF_PRODUCT_NAME, CONF_PRODUCT_TYPE, CONF_SERIAL, DOMAIN

_LOGGER = logging.getLogger(__name__)


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for P1 meter."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize the HomeWizard config flow."""
        self.config: dict[str, str | int] = {}

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle a flow initiated by the user."""

        _LOGGER.debug("config_flow async_step_user")

        if user_input is None:
            return self.async_show_form(
                step_id="user",
                data_schema=Schema(
                    {
                        Required(CONF_IP_ADDRESS): str,
                    }
                ),
                errors=None,
            )

        device_info = await self._async_try_connect_and_fetch(
            user_input[CONF_IP_ADDRESS]
        )

        # Sets unique ID and aborts if it is already exists
        await self._async_set_and_check_unique_id(
            {
                CONF_IP_ADDRESS: user_input[CONF_IP_ADDRESS],
                CONF_PRODUCT_TYPE: device_info[CONF_PRODUCT_TYPE],
                CONF_SERIAL: device_info[CONF_SERIAL],
            }
        )

        # Add entry
        return self.async_create_entry(
            title=f"{device_info[CONF_PRODUCT_NAME]} ({device_info[CONF_SERIAL]})",
            data={
                CONF_IP_ADDRESS: user_input[CONF_IP_ADDRESS],
            },
        )

    async def async_step_zeroconf(
        self, discovery_info: zeroconf.ZeroconfServiceInfo
    ) -> FlowResult:
        """Handle zeroconf discovery."""

        _LOGGER.debug("config_flow async_step_zeroconf")

        # Validate doscovery entry
        if (
            "api_enabled" not in discovery_info.properties
            or "path" not in discovery_info.properties
            or "product_name" not in discovery_info.properties
            or "product_type" not in discovery_info.properties
            or "serial" not in discovery_info.properties
        ):
            return self.async_abort(reason="invalid_discovery_parameters")

        if (discovery_info.properties["path"]) != "/api/v1":
            return self.async_abort(reason="unsupported_api_version")

        if (discovery_info.properties["api_enabled"]) != "1":
            return self.async_abort(reason="api_not_enabled")

        # Sets unique ID and aborts if it is already exists
        await self._async_set_and_check_unique_id(
            {
                CONF_IP_ADDRESS: discovery_info.host,
                CONF_PRODUCT_TYPE: discovery_info.properties["product_type"],
                CONF_SERIAL: discovery_info.properties["serial"],
            }
        )

        # Check connection and fetch
        device_info: dict[str, Any] = await self._async_try_connect_and_fetch(
            discovery_info.host
        )

        # Pass parameters
        self.config = {
            CONF_IP_ADDRESS: discovery_info.host,
            CONF_PRODUCT_TYPE: device_info[CONF_PRODUCT_TYPE],
            CONF_PRODUCT_NAME: device_info[CONF_PRODUCT_NAME],
            CONF_SERIAL: device_info[CONF_SERIAL],
        }
        return await self.async_step_discovery_confirm()

    async def async_step_discovery_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Confirm discovery."""
        if user_input is not None:
            return self.async_create_entry(
                title=f"{self.config[CONF_PRODUCT_NAME]} ({self.config[CONF_SERIAL]})",
                data={
                    CONF_IP_ADDRESS: self.config[CONF_IP_ADDRESS],
                },
            )

        self._set_confirm_only()

        self.context["title_placeholders"] = {
            "name": f"{self.config[CONF_PRODUCT_NAME]} ({self.config[CONF_SERIAL]})"
        }

        return self.async_show_form(
            step_id="discovery_confirm",
            description_placeholders={
                CONF_PRODUCT_TYPE: self.config[CONF_PRODUCT_TYPE],
                CONF_SERIAL: self.config[CONF_SERIAL],
                CONF_IP_ADDRESS: self.config[CONF_IP_ADDRESS],
            },
        )

    @staticmethod
    async def _async_try_connect_and_fetch(ip_address: str) -> dict[str, Any]:
        """Try to connect."""

        _LOGGER.debug("config_flow _async_try_connect_and_fetch")

        # Make connection with device
        # This is to test the connection and to get info for unique_id
        energy_api = aiohwenergy.HomeWizardEnergy(ip_address)

        try:
            with async_timeout.timeout(10):
                await energy_api.initialize()

        except aiohwenergy.DisabledError as ex:
            _LOGGER.error("API disabled, API must be enabled in the app")
            raise AbortFlow("api_not_enabled") from ex

        except Exception as ex:
            _LOGGER.exception(
                "Error connecting with Energy Device at %s",
                ip_address,
            )
            raise AbortFlow("unknown_error") from ex

        finally:
            await energy_api.close()

        if energy_api.device is None:
            _LOGGER.error("Initialization failed")
            raise AbortFlow("unknown_error")

        # Validate metadata
        if energy_api.device.api_version != "v1":
            raise AbortFlow("unsupported_api_version")

        if energy_api.device.product_type not in SUPPORTED_DEVICES:
            _LOGGER.error(
                "Device (%s) not supported by integration",
                energy_api.device.product_type,
            )
            raise AbortFlow("device_not_supported")

        return {
            CONF_PRODUCT_NAME: energy_api.device.product_name,
            CONF_PRODUCT_TYPE: energy_api.device.product_type,
            CONF_SERIAL: energy_api.device.serial,
        }

    async def _async_set_and_check_unique_id(self, entry_info: dict[str, Any]) -> None:
        """Validate if entry exists."""

        _LOGGER.debug("config_flow _async_set_and_check_unique_id")

        await self.async_set_unique_id(
            f"{entry_info[CONF_PRODUCT_TYPE]}_{entry_info[CONF_SERIAL]}"
        )
        self._abort_if_unique_id_configured(
            updates={CONF_IP_ADDRESS: entry_info[CONF_IP_ADDRESS]}
        )
