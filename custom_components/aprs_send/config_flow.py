"""Config flow for the APRS Position Sender integration."""

from __future__ import annotations

import logging
from typing import Any

import aprslib.exceptions
import voluptuous as vol

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import selector

from .aprs import (
    is_valid_callsign,
    normalize_callsign,
    passcode_matches,
    test_connection,
)
from .const import (
    CONF_CALLSIGN,
    CONF_COMMENT,
    CONF_ENTITY_ID,
    CONF_HOST,
    CONF_MAX_INTERVAL_S,
    CONF_MIN_DISTANCE_M,
    CONF_MIN_INTERVAL_S,
    CONF_PASSCODE,
    CONF_PORT,
    CONF_SPEED_UNIT,
    CONF_SYMBOL_CODE,
    CONF_SYMBOL_TABLE,
    DEFAULT_COMMENT,
    DEFAULT_HOST,
    DEFAULT_MAX_INTERVAL_S,
    DEFAULT_MIN_DISTANCE_M,
    DEFAULT_MIN_INTERVAL_S,
    DEFAULT_PORT,
    DEFAULT_SPEED_UNIT,
    DEFAULT_SYMBOL_CODE,
    DEFAULT_SYMBOL_TABLE,
    DOMAIN,
    MAX_COMMENT_LENGTH,
    SPEED_UNITS,
)

_LOGGER = logging.getLogger(__name__)

_SINGLE_CHAR = vol.All(str, vol.Length(min=1, max=1))


def _options_schema(current: dict[str, Any]) -> vol.Schema:
    """Schema for the tunable fields, shared by config and options flow."""
    return vol.Schema(
        {
            vol.Optional(CONF_HOST, default=current.get(CONF_HOST, DEFAULT_HOST)): str,
            vol.Optional(
                CONF_PORT, default=current.get(CONF_PORT, DEFAULT_PORT)
            ): vol.All(vol.Coerce(int), vol.Range(min=1, max=65535)),
            vol.Optional(
                CONF_COMMENT, default=current.get(CONF_COMMENT, DEFAULT_COMMENT)
            ): vol.All(str, vol.Length(max=MAX_COMMENT_LENGTH)),
            vol.Optional(
                CONF_SYMBOL_TABLE,
                default=current.get(CONF_SYMBOL_TABLE, DEFAULT_SYMBOL_TABLE),
            ): _SINGLE_CHAR,
            vol.Optional(
                CONF_SYMBOL_CODE,
                default=current.get(CONF_SYMBOL_CODE, DEFAULT_SYMBOL_CODE),
            ): _SINGLE_CHAR,
            vol.Optional(
                CONF_MIN_DISTANCE_M,
                default=current.get(CONF_MIN_DISTANCE_M, DEFAULT_MIN_DISTANCE_M),
            ): vol.All(vol.Coerce(int), vol.Range(min=0)),
            vol.Optional(
                CONF_MIN_INTERVAL_S,
                default=current.get(CONF_MIN_INTERVAL_S, DEFAULT_MIN_INTERVAL_S),
            ): vol.All(vol.Coerce(int), vol.Range(min=0)),
            vol.Optional(
                CONF_MAX_INTERVAL_S,
                default=current.get(CONF_MAX_INTERVAL_S, DEFAULT_MAX_INTERVAL_S),
            ): vol.All(vol.Coerce(int), vol.Range(min=10)),
            vol.Optional(
                CONF_SPEED_UNIT,
                default=current.get(CONF_SPEED_UNIT, DEFAULT_SPEED_UNIT),
            ): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=SPEED_UNITS,
                    translation_key="speed_unit",
                    mode=selector.SelectSelectorMode.DROPDOWN,
                )
            ),
        }
    )


def _user_schema(current: dict[str, Any]) -> vol.Schema:
    """Schema for the initial setup step."""
    entity_field = (
        vol.Required(CONF_ENTITY_ID, default=current[CONF_ENTITY_ID])
        if CONF_ENTITY_ID in current
        else vol.Required(CONF_ENTITY_ID)
    )
    base = vol.Schema(
        {
            vol.Required(CONF_CALLSIGN, default=current.get(CONF_CALLSIGN, "")): str,
            vol.Required(CONF_PASSCODE, default=current.get(CONF_PASSCODE, "")): str,
            entity_field: selector.EntitySelector(
                selector.EntitySelectorConfig(domain="device_tracker")
            ),
        }
    )
    return base.extend(_options_schema(current).schema)


async def _async_validate(hass: HomeAssistant, data: dict[str, Any]) -> dict[str, str]:
    """Validate credentials and connectivity. Returns a dict of form errors."""
    errors: dict[str, str] = {}
    callsign = data[CONF_CALLSIGN]

    if not is_valid_callsign(callsign):
        errors[CONF_CALLSIGN] = "invalid_callsign"
        return errors
    if not passcode_matches(callsign, data[CONF_PASSCODE]):
        errors[CONF_PASSCODE] = "invalid_auth"
        return errors

    try:
        await hass.async_add_executor_job(
            test_connection,
            callsign,
            data[CONF_PASSCODE],
            data[CONF_HOST],
            data[CONF_PORT],
        )
    except aprslib.exceptions.LoginError:
        errors["base"] = "invalid_auth"
    except (aprslib.exceptions.ConnectionError, OSError, TimeoutError):
        errors["base"] = "cannot_connect"
    except Exception:  # noqa: BLE001
        _LOGGER.exception("Unexpected error validating APRS-IS connection")
        errors["base"] = "unknown"
    return errors


class AprsSendConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle the UI setup of an APRS Position Sender entry."""

    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> AprsSendOptionsFlow:
        """Return the options flow handler."""
        return AprsSendOptionsFlow()

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}
        current: dict[str, Any] = user_input or {}

        if user_input is not None:
            user_input[CONF_CALLSIGN] = normalize_callsign(user_input[CONF_CALLSIGN])
            user_input[CONF_PASSCODE] = str(user_input[CONF_PASSCODE]).strip()
            user_input[CONF_HOST] = user_input[CONF_HOST].strip() or DEFAULT_HOST

            await self.async_set_unique_id(
                f"{user_input[CONF_CALLSIGN]}_{user_input[CONF_ENTITY_ID]}"
            )
            self._abort_if_unique_id_configured()

            errors = await _async_validate(self.hass, user_input)
            if not errors:
                return self.async_create_entry(
                    title=f"{user_input[CONF_CALLSIGN]} ({user_input[CONF_ENTITY_ID]})",
                    data=user_input,
                )

        return self.async_show_form(
            step_id="user", data_schema=_user_schema(current), errors=errors
        )


class AprsSendOptionsFlow(OptionsFlow):
    """Allow changing the tunable fields without re-creating the entry."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Manage the options."""
        if user_input is not None:
            user_input[CONF_HOST] = user_input[CONF_HOST].strip() or DEFAULT_HOST
            return self.async_create_entry(title="", data=user_input)

        current = {**self.config_entry.data, **self.config_entry.options}
        return self.async_show_form(
            step_id="init", data_schema=_options_schema(current)
        )
