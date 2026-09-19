"""Tests for the beaconing switch."""

from __future__ import annotations

from datetime import timedelta
from unittest.mock import MagicMock

from freezegun.api import FrozenDateTimeFactory
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
    mock_restore_cache,
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
from homeassistant.components.switch import DOMAIN as SWITCH_DOMAIN
from homeassistant.const import (
    ATTR_ENTITY_ID,
    SERVICE_TURN_OFF,
    SERVICE_TURN_ON,
    STATE_OFF,
    STATE_ON,
)
from homeassistant.core import HomeAssistant, State
from homeassistant.helpers import entity_registry as er

TRACKER = "device_tracker.test"
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
            CONF_COMMENT: "",
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


async def _switch(hass: HomeAssistant, service: str) -> None:
    await hass.services.async_call(
        SWITCH_DOMAIN, service, {ATTR_ENTITY_ID: SWITCH}, blocking=True
    )
    await hass.async_block_till_done()


async def test_switch_created_on(
    hass: HomeAssistant, mock_send_packet: MagicMock
) -> None:
    """The switch exists, is on by default and belongs to the entry's device."""
    _set_position(hass, LAT0, LON0)
    entry = await _setup(hass)

    state = hass.states.get(SWITCH)
    assert state is not None
    assert state.state == STATE_ON
    assert mock_send_packet.call_count == 1

    registry = er.async_get(hass)
    reg_entry = registry.async_get(SWITCH)
    assert reg_entry is not None
    assert reg_entry.unique_id == f"{entry.entry_id}_beaconing"
    assert reg_entry.device_id is not None


async def test_turn_off_stops_sending(
    hass: HomeAssistant, mock_send_packet: MagicMock, freezer: FrozenDateTimeFactory
) -> None:
    """While off neither movement nor the heartbeat sends anything."""
    _set_position(hass, LAT0, LON0)
    await _setup(hass)
    assert mock_send_packet.call_count == 1

    await _switch(hass, SERVICE_TURN_OFF)
    assert hass.states.get(SWITCH).state == STATE_OFF

    freezer.tick(timedelta(seconds=60))
    _set_position(hass, LAT0 + 0.01, LON0)
    await hass.async_block_till_done()
    freezer.tick(timedelta(seconds=700))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert mock_send_packet.call_count == 1


async def test_turn_on_sends_latest_position_and_restarts_heartbeat(
    hass: HomeAssistant, mock_send_packet: MagicMock, freezer: FrozenDateTimeFactory
) -> None:
    """Turning on beacons the position noted while off, then heartbeats again."""
    _set_position(hass, LAT0, LON0)
    await _setup(hass)
    await _switch(hass, SERVICE_TURN_OFF)

    freezer.tick(timedelta(seconds=60))
    _set_position(hass, LAT0 + 0.01, LON0)
    await hass.async_block_till_done()
    assert mock_send_packet.call_count == 1

    await _switch(hass, SERVICE_TURN_ON)
    assert hass.states.get(SWITCH).state == STATE_ON
    assert mock_send_packet.call_count == 2
    assert "4657.49N" in mock_send_packet.call_args.args[4]

    freezer.tick(timedelta(seconds=601))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert mock_send_packet.call_count == 3


async def test_off_state_restored_after_restart(
    hass: HomeAssistant, mock_send_packet: MagicMock
) -> None:
    """A switch that was off before a restart stays off and sends nothing."""
    mock_restore_cache(hass, [State(SWITCH, STATE_OFF)])
    _set_position(hass, LAT0, LON0)
    await _setup(hass)

    assert hass.states.get(SWITCH).state == STATE_OFF
    mock_send_packet.assert_not_called()

    await _switch(hass, SERVICE_TURN_ON)
    assert mock_send_packet.call_count == 1


SPEED_SWITCH = "switch.aprs_n0call_9_send_speed_and_course"
ALT_SWITCH = "switch.aprs_n0call_9_send_altitude"


def _set_rich_position(hass: HomeAssistant) -> None:
    """Position with speed (m/s), course and altitude as the Companion app sends."""
    hass.states.async_set(
        TRACKER,
        "not_home",
        {
            "latitude": LAT0,
            "longitude": LON0,
            "speed": 23.15,  # m/s = 45 kn
            "course": 88,
            "altitude": 540,
            "source_type": "gps",
        },
    )


async def _svc(hass: HomeAssistant, entity_id: str, service: str) -> None:
    await hass.services.async_call(
        SWITCH_DOMAIN, service, {ATTR_ENTITY_ID: entity_id}, blocking=True
    )
    await hass.async_block_till_done()


async def test_extra_fields_sent_by_default(
    hass: HomeAssistant, mock_send_packet: MagicMock
) -> None:
    """Speed/course and altitude are included when the tracker provides them."""
    _set_rich_position(hass)
    await _setup(hass)

    assert hass.states.get(SPEED_SWITCH).state == STATE_ON
    assert hass.states.get(ALT_SWITCH).state == STATE_ON
    packet = mock_send_packet.call_args.args[4]
    assert packet.endswith("E>088/045/A=001772")


async def test_extra_field_switches(
    hass: HomeAssistant, mock_send_packet: MagicMock, freezer: FrozenDateTimeFactory
) -> None:
    """Each switch removes its field from the next report without sending."""
    _set_rich_position(hass)
    await _setup(hass)
    assert mock_send_packet.call_count == 1

    await _svc(hass, SPEED_SWITCH, SERVICE_TURN_OFF)
    assert hass.states.get(SPEED_SWITCH).state == STATE_OFF
    assert mock_send_packet.call_count == 1  # toggling alone does not send

    freezer.tick(timedelta(seconds=601))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert mock_send_packet.call_count == 2
    assert mock_send_packet.call_args.args[4].endswith("E>/A=001772")

    await _svc(hass, ALT_SWITCH, SERVICE_TURN_OFF)
    await _svc(hass, SPEED_SWITCH, SERVICE_TURN_ON)
    freezer.tick(timedelta(seconds=601))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert mock_send_packet.call_count == 3
    assert mock_send_packet.call_args.args[4].endswith("E>088/045")


async def test_extra_field_switches_restored(
    hass: HomeAssistant, mock_send_packet: MagicMock
) -> None:
    """Switched-off fields stay off after a restart, already for the first packet."""
    mock_restore_cache(
        hass, [State(SPEED_SWITCH, STATE_OFF), State(ALT_SWITCH, STATE_OFF)]
    )
    _set_rich_position(hass)
    await _setup(hass)

    assert hass.states.get(SPEED_SWITCH).state == STATE_OFF
    assert hass.states.get(ALT_SWITCH).state == STATE_OFF
    assert mock_send_packet.call_args.args[4].endswith("E>")


async def test_speed_unit_option(
    hass: HomeAssistant, mock_send_packet: MagicMock
) -> None:
    """The speed attribute is converted according to the configured unit."""
    entry = _entry()
    entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(entry, options={"speed_unit": "kmh"})
    hass.states.async_set(
        TRACKER,
        "not_home",
        {"latitude": LAT0, "longitude": LON0, "speed": 100, "source_type": "gps"},
    )
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    # 100 km/h = 54 kn, no course -> 000
    assert mock_send_packet.call_args.args[4].endswith("E>000/054")
