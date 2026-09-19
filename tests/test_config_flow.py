"""Tests for the aprs_send config and options flow."""

from __future__ import annotations

from unittest.mock import MagicMock

import aprslib.exceptions
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.aprs_send.const import (
    CONF_CALLSIGN,
    CONF_COMMENT,
    CONF_ENTITY_ID,
    CONF_HOST,
    CONF_MAX_INTERVAL_S,
    CONF_MIN_DISTANCE_M,
    CONF_MIN_INTERVAL_S,
    CONF_PASSCODE,
    CONF_PORT,
    CONF_SYMBOL_CODE,
    CONF_SYMBOL_TABLE,
    DEFAULT_HOST,
    DEFAULT_PORT,
    DOMAIN,
)
from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

# N0CALL -> passcode 13023
USER_INPUT = {
    CONF_CALLSIGN: " n0call-9 ",
    CONF_PASSCODE: "13023",
    CONF_ENTITY_ID: "device_tracker.test",
}


async def _start_flow(hass: HomeAssistant) -> dict:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"
    assert result["errors"] == {}
    return result


async def test_user_flow_success(
    hass: HomeAssistant, mock_test_connection: MagicMock, mock_send_packet: MagicMock
) -> None:
    """A valid form creates an entry with normalised data and defaults."""
    result = await _start_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input=USER_INPUT
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "N0CALL-9 (device_tracker.test)"
    data = result["data"]
    assert data[CONF_CALLSIGN] == "N0CALL-9"
    assert data[CONF_PASSCODE] == "13023"
    assert data[CONF_HOST] == DEFAULT_HOST
    assert data[CONF_PORT] == DEFAULT_PORT
    assert data[CONF_SYMBOL_TABLE] == "/"
    assert data[CONF_SYMBOL_CODE] == ">"
    assert data[CONF_MIN_DISTANCE_M] == 100
    assert data[CONF_MIN_INTERVAL_S] == 30
    assert data[CONF_MAX_INTERVAL_S] == 600
    assert result["result"].unique_id == "N0CALL-9_device_tracker.test"

    mock_test_connection.assert_called_once_with(
        "N0CALL-9", "13023", DEFAULT_HOST, DEFAULT_PORT
    )


async def test_user_flow_invalid_callsign(
    hass: HomeAssistant, mock_test_connection: MagicMock
) -> None:
    """A malformed callsign is rejected before any network access."""
    result = await _start_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input={**USER_INPUT, CONF_CALLSIGN: "N0CALL-"}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {CONF_CALLSIGN: "invalid_callsign"}
    mock_test_connection.assert_not_called()


async def test_user_flow_wrong_passcode(
    hass: HomeAssistant, mock_test_connection: MagicMock
) -> None:
    """A passcode not matching the callsign is rejected locally."""
    result = await _start_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input={**USER_INPUT, CONF_PASSCODE: "12345"}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {CONF_PASSCODE: "invalid_auth"}
    mock_test_connection.assert_not_called()


@pytest.mark.parametrize(
    ("exc", "error"),
    [
        (aprslib.exceptions.LoginError("nope"), "invalid_auth"),
        (aprslib.exceptions.ConnectionError("down"), "cannot_connect"),
        (OSError("refused"), "cannot_connect"),
        (RuntimeError("weird"), "unknown"),
    ],
)
async def test_user_flow_connection_errors(
    hass: HomeAssistant, mock_test_connection: MagicMock, exc: Exception, error: str
) -> None:
    """Server-side failures map to form errors and the form is shown again."""
    mock_test_connection.side_effect = exc
    result = await _start_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input=USER_INPUT
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": error}


async def test_user_flow_duplicate_aborts(
    hass: HomeAssistant, mock_test_connection: MagicMock
) -> None:
    """The same callsign + tracker cannot be configured twice."""
    MockConfigEntry(
        domain=DOMAIN,
        unique_id="N0CALL-9_device_tracker.test",
        data={**USER_INPUT, CONF_CALLSIGN: "N0CALL-9"},
    ).add_to_hass(hass)

    result = await _start_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input=USER_INPUT
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_options_flow(
    hass: HomeAssistant, mock_send_packet: MagicMock
) -> None:
    """Options can be changed and the entry is reloaded."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="N0CALL-9_device_tracker.test",
        data={
            CONF_CALLSIGN: "N0CALL-9",
            CONF_PASSCODE: "13023",
            CONF_ENTITY_ID: "device_tracker.test",
            CONF_HOST: DEFAULT_HOST,
            CONF_PORT: DEFAULT_PORT,
        },
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "init"

    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        user_input={
            CONF_HOST: "euro.aprs2.net",
            CONF_PORT: 14580,
            CONF_COMMENT: "HA relay",
            CONF_SYMBOL_TABLE: "/",
            CONF_SYMBOL_CODE: "[",
            CONF_MIN_DISTANCE_M: 50,
            CONF_MIN_INTERVAL_S: 10,
            CONF_MAX_INTERVAL_S: 300,
        },
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options[CONF_HOST] == "euro.aprs2.net"
    assert entry.options[CONF_MIN_DISTANCE_M] == 50
    assert entry.state is config_entries.ConfigEntryState.LOADED
    # The reloaded sender picked up the new options.
    assert entry.runtime_data._host == "euro.aprs2.net"
    assert entry.runtime_data._min_distance_m == 50
