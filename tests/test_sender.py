"""Tests for the smart-broadcast sender logic."""

from __future__ import annotations

from datetime import timedelta
from unittest.mock import MagicMock

import aprslib.exceptions
from freezegun.api import FrozenDateTimeFactory
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)

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
    DOMAIN,
)
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant

TRACKER = "device_tracker.test"
CALLSIGN = "N0CALL-9"
PASSCODE = "13023"
HOST = "rotate.aprs2.net"
PORT = 14580

# Roughly 111 m per 0.001 degree of latitude.
LAT0, LON0 = 46.9481, 7.4474


def _entry() -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN,
        unique_id=f"{CALLSIGN}_{TRACKER}",
        data={
            CONF_CALLSIGN: CALLSIGN,
            CONF_PASSCODE: PASSCODE,
            CONF_ENTITY_ID: TRACKER,
            CONF_HOST: HOST,
            CONF_PORT: PORT,
            CONF_COMMENT: "test",
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
    assert entry.state is ConfigEntryState.LOADED
    return entry


def _sent_packets(mock: MagicMock) -> list[str]:
    return [call.args[4] for call in mock.call_args_list]


async def test_initial_position_sent_immediately(
    hass: HomeAssistant, mock_send_packet: MagicMock
) -> None:
    """A tracker that already has a fix is beaconed right at setup."""
    _set_position(hass, LAT0, LON0)
    await _setup(hass)

    mock_send_packet.assert_called_once()
    args = mock_send_packet.call_args.args
    assert args[:4] == (CALLSIGN, PASSCODE, HOST, PORT)
    assert args[4] == "N0CALL-9>APRS,TCPIP*:!4656.89N/00726.84E>test"


async def test_waits_for_first_fix(
    hass: HomeAssistant, mock_send_packet: MagicMock
) -> None:
    """Without coordinates nothing is sent; the first fix is sent at once."""
    hass.states.async_set(TRACKER, "unknown", {"source_type": "gps"})
    await _setup(hass)
    mock_send_packet.assert_not_called()

    _set_position(hass, LAT0, LON0)
    await hass.async_block_till_done()
    mock_send_packet.assert_called_once()


async def test_small_movement_not_sent(
    hass: HomeAssistant, mock_send_packet: MagicMock, freezer: FrozenDateTimeFactory
) -> None:
    """Movement below min_distance is ignored even after min_interval."""
    _set_position(hass, LAT0, LON0)
    await _setup(hass)
    assert mock_send_packet.call_count == 1

    freezer.tick(timedelta(seconds=60))
    _set_position(hass, LAT0 + 0.0005, LON0)  # ~55 m
    await hass.async_block_till_done()
    assert mock_send_packet.call_count == 1


async def test_movement_within_min_interval_not_sent(
    hass: HomeAssistant, mock_send_packet: MagicMock, freezer: FrozenDateTimeFactory
) -> None:
    """A large jump right after a report is held back by min_interval."""
    _set_position(hass, LAT0, LON0)
    await _setup(hass)
    assert mock_send_packet.call_count == 1

    freezer.tick(timedelta(seconds=10))
    _set_position(hass, LAT0 + 0.002, LON0)  # ~220 m
    await hass.async_block_till_done()
    assert mock_send_packet.call_count == 1

    # Once min_interval has passed the next movement is sent, and the
    # distance is measured against the last *sent* position.
    freezer.tick(timedelta(seconds=25))
    _set_position(hass, LAT0 + 0.0021, LON0)
    await hass.async_block_till_done()
    assert mock_send_packet.call_count == 2
    # 46.9502 deg = 46 deg 57.012 min
    assert _sent_packets(mock_send_packet)[1].startswith(
        "N0CALL-9>APRS,TCPIP*:!4657.01N"
    )


async def test_large_movement_sent(
    hass: HomeAssistant, mock_send_packet: MagicMock, freezer: FrozenDateTimeFactory
) -> None:
    """Movement beyond min_distance after min_interval is sent."""
    _set_position(hass, LAT0, LON0)
    await _setup(hass)

    freezer.tick(timedelta(seconds=31))
    _set_position(hass, LAT0 + 0.002, LON0)
    await hass.async_block_till_done()
    assert mock_send_packet.call_count == 2


async def test_heartbeat_without_movement(
    hass: HomeAssistant, mock_send_packet: MagicMock, freezer: FrozenDateTimeFactory
) -> None:
    """The last known position is re-sent every max_interval."""
    _set_position(hass, LAT0, LON0)
    await _setup(hass)
    assert mock_send_packet.call_count == 1

    freezer.tick(timedelta(seconds=599))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert mock_send_packet.call_count == 1

    freezer.tick(timedelta(seconds=2))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert mock_send_packet.call_count == 2

    packets = _sent_packets(mock_send_packet)
    assert packets[0] == packets[1]

    # Heartbeat re-arms itself.
    freezer.tick(timedelta(seconds=601))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert mock_send_packet.call_count == 3


async def test_heartbeat_uses_latest_known_position(
    hass: HomeAssistant, mock_send_packet: MagicMock, freezer: FrozenDateTimeFactory
) -> None:
    """Small moves that were not sent are still reflected in the heartbeat."""
    _set_position(hass, LAT0, LON0)
    await _setup(hass)

    freezer.tick(timedelta(seconds=60))
    _set_position(hass, LAT0 + 0.0005, LON0)  # ~55 m, not sent
    await hass.async_block_till_done()
    assert mock_send_packet.call_count == 1

    freezer.tick(timedelta(seconds=541))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert mock_send_packet.call_count == 2
    assert "4656.92N" in _sent_packets(mock_send_packet)[1]


async def test_send_failure_is_logged_and_retried(
    hass: HomeAssistant,
    mock_send_packet: MagicMock,
    freezer: FrozenDateTimeFactory,
    caplog,
) -> None:
    """Network errors never raise; the next trigger retries."""
    mock_send_packet.side_effect = aprslib.exceptions.ConnectionError("down")
    _set_position(hass, LAT0, LON0)
    entry = await _setup(hass)
    assert entry.state is ConfigEntryState.LOADED
    assert "could not reach APRS-IS" in caplog.text
    assert mock_send_packet.call_count == 1

    # Nothing was ever sent successfully, so the next fix is sent at once
    # regardless of distance or interval.
    mock_send_packet.side_effect = None
    _set_position(hass, LAT0 + 0.0001, LON0)
    await hass.async_block_till_done()
    assert mock_send_packet.call_count == 2

    # Login failures are logged as well.
    mock_send_packet.side_effect = aprslib.exceptions.LoginError("bad")
    freezer.tick(timedelta(seconds=601))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert "rejected login" in caplog.text


async def test_unload_stops_everything(
    hass: HomeAssistant, mock_send_packet: MagicMock, freezer: FrozenDateTimeFactory
) -> None:
    """After unload neither state changes nor timers cause sends."""
    _set_position(hass, LAT0, LON0)
    entry = await _setup(hass)
    assert mock_send_packet.call_count == 1

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.NOT_LOADED

    freezer.tick(timedelta(seconds=60))
    _set_position(hass, LAT0 + 0.01, LON0)
    await hass.async_block_till_done()
    freezer.tick(timedelta(seconds=700))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert mock_send_packet.call_count == 1


async def test_reload_does_not_double_track(
    hass: HomeAssistant, mock_send_packet: MagicMock, freezer: FrozenDateTimeFactory
) -> None:
    """Reloading the entry replaces the listeners instead of adding to them."""
    _set_position(hass, LAT0, LON0)
    entry = await _setup(hass)
    assert mock_send_packet.call_count == 1

    await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED
    # Fresh sender sends the initial position again.
    assert mock_send_packet.call_count == 2

    freezer.tick(timedelta(seconds=31))
    _set_position(hass, LAT0 + 0.002, LON0)
    await hass.async_block_till_done()
    # Exactly one more send, not two.
    assert mock_send_packet.call_count == 3
