"""Tests for the send-now button."""

from __future__ import annotations

from datetime import timedelta
from unittest.mock import MagicMock

import aprslib.exceptions
from freezegun.api import FrozenDateTimeFactory
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.aprs_send.const import (
    CONF_CALLSIGN,
    CONF_ENTITY_ID,
    CONF_HOST,
    CONF_MAX_INTERVAL_S,
    CONF_MIN_DISTANCE_M,
    CONF_MIN_INTERVAL_S,
    CONF_PASSCODE,
    CONF_PORT,
    DOMAIN,
)
from homeassistant.components.button import DOMAIN as BUTTON_DOMAIN, SERVICE_PRESS
from homeassistant.components.switch import DOMAIN as SWITCH_DOMAIN
from homeassistant.const import ATTR_ENTITY_ID, SERVICE_TURN_OFF
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError

TRACKER = "device_tracker.test"
BUTTON = "button.aprs_n0call_9_send_position_now"
SWITCH = "switch.aprs_n0call_9_beaconing"
LAT0, LON0 = 46.9481, 7.4474


def _entry() -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN,
        entry_id="test_entry",
        unique_id=f"N0CALL-9_{TRACKER}",
        data={
            CONF_CALLSIGN: "N0CALL-9",
            CONF_PASSCODE: "13023",
            CONF_ENTITY_ID: TRACKER,
            CONF_HOST: "rotate.aprs2.net",
            CONF_PORT: 14580,
            CONF_MIN_DISTANCE_M: 100,
            CONF_MIN_INTERVAL_S: 30,
            CONF_MAX_INTERVAL_S: 600,
        },
    )


def _set_position(hass: HomeAssistant, lat: float, lon: float) -> None:
    hass.states.async_set(
        TRACKER, "not_home", {"latitude": lat, "longitude": lon, "source_type": "gps"}
    )


async def _setup(hass: HomeAssistant) -> MockConfigEntry:
    entry = _entry()
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def _press(hass: HomeAssistant) -> None:
    await hass.services.async_call(
        BUTTON_DOMAIN, SERVICE_PRESS, {ATTR_ENTITY_ID: BUTTON}, blocking=True
    )
    await hass.async_block_till_done()


async def test_press_sends_ignoring_thresholds(
    hass: HomeAssistant, mock_send_packet: MagicMock, freezer: FrozenDateTimeFactory
) -> None:
    """A press sends right away even without movement or elapsed interval."""
    _set_position(hass, LAT0, LON0)
    await _setup(hass)
    assert hass.states.get(BUTTON) is not None
    assert mock_send_packet.call_count == 1

    freezer.tick(timedelta(seconds=5))
    await _press(hass)
    assert mock_send_packet.call_count == 2

    # The manual send counts as the last report for the thresholds.
    freezer.tick(timedelta(seconds=10))
    _set_position(hass, LAT0 + 0.002, LON0)
    await hass.async_block_till_done()
    assert mock_send_packet.call_count == 2


async def test_press_uses_latest_position_and_ignores_switch(
    hass: HomeAssistant, mock_send_packet: MagicMock, freezer: FrozenDateTimeFactory
) -> None:
    """Pressing while beaconing is off still sends the newest position."""
    _set_position(hass, LAT0, LON0)
    await _setup(hass)
    await hass.services.async_call(
        SWITCH_DOMAIN, SERVICE_TURN_OFF, {ATTR_ENTITY_ID: SWITCH}, blocking=True
    )
    freezer.tick(timedelta(seconds=60))
    _set_position(hass, LAT0 + 0.01, LON0)
    await hass.async_block_till_done()
    assert mock_send_packet.call_count == 1

    await _press(hass)
    assert mock_send_packet.call_count == 2
    assert "4657.49N" in mock_send_packet.call_args.args[4]


async def test_press_without_position_raises(
    hass: HomeAssistant, mock_send_packet: MagicMock
) -> None:
    """Without a known position the press fails visibly."""
    hass.states.async_set(TRACKER, "unknown", {"source_type": "gps"})
    await _setup(hass)

    with pytest.raises(HomeAssistantError, match="no position known"):
        await _press(hass)
    mock_send_packet.assert_not_called()


async def test_press_send_failure_raises(
    hass: HomeAssistant, mock_send_packet: MagicMock
) -> None:
    """A failed transmission is reported to the caller."""
    _set_position(hass, LAT0, LON0)
    await _setup(hass)
    mock_send_packet.side_effect = aprslib.exceptions.ConnectionError("down")

    with pytest.raises(HomeAssistantError, match="failed"):
        await _press(hass)
