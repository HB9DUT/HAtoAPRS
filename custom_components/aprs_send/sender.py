"""Smart-broadcast logic: watch a device_tracker and send APRS position reports."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta
import logging
from typing import Any

import aprslib.exceptions

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_LATITUDE, ATTR_LONGITUDE
from homeassistant.core import CALLBACK_TYPE, Event, HomeAssistant, State, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.event import (
    EventStateChangedData,
    async_call_later,
    async_track_state_change_event,
)
from homeassistant.util import dt as dt_util

from .aprs import build_position_packet, haversine_m, send_packet
from .const import (
    ATTR_ALTITUDE,
    ATTR_COURSE,
    ATTR_SPEED,
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
    SPEED_UNIT_KMH,
    SPEED_UNIT_KN,
    SPEED_UNIT_MPH,
    SPEED_UNIT_MS,
)

_LOGGER = logging.getLogger(__name__)

Position = tuple[float, float]

# Factors to convert the tracker's speed attribute to knots.
_TO_KNOTS: dict[str, float] = {
    SPEED_UNIT_MS: 1.943844,
    SPEED_UNIT_KMH: 0.539957,
    SPEED_UNIT_KN: 1.0,
    SPEED_UNIT_MPH: 0.868976,
}


@dataclass(frozen=True, slots=True)
class Fix:
    """A position with the optional extras a tracker may provide."""

    lat: float
    lon: float
    speed_kn: float | None = None
    course: float | None = None
    altitude_m: float | None = None

    @property
    def position(self) -> Position:
        """Return (lat, lon)."""
        return (self.lat, self.lon)


def _float_or_none(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _fix_from_state(state: State | None, speed_unit: str) -> Fix | None:
    """Extract a Fix from a state, or None if there is no valid position."""
    if state is None:
        return None
    lat = _float_or_none(state.attributes.get(ATTR_LATITUDE))
    lon = _float_or_none(state.attributes.get(ATTR_LONGITUDE))
    if lat is None or lon is None:
        return None
    if not (-90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0):
        return None

    speed = _float_or_none(state.attributes.get(ATTR_SPEED))
    if speed is not None and speed < 0:
        speed = None
    course = _float_or_none(state.attributes.get(ATTR_COURSE))
    if course is not None and not (0.0 <= course <= 360.0):
        course = None
    altitude = _float_or_none(state.attributes.get(ATTR_ALTITUDE))

    return Fix(
        lat=lat,
        lon=lon,
        speed_kn=None if speed is None else speed * _TO_KNOTS[speed_unit],
        course=course,
        altitude_m=altitude,
    )


class AprsPositionSender:
    """Track one device_tracker entity and beacon its position to APRS-IS."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialise from the merged config entry data and options."""
        self._hass = hass
        self._entry = entry
        config: dict[str, Any] = {**entry.data, **entry.options}

        self._callsign: str = config[CONF_CALLSIGN]
        self._passcode: str = str(config[CONF_PASSCODE])
        self._entity_id: str = config[CONF_ENTITY_ID]
        self._host: str = config.get(CONF_HOST, DEFAULT_HOST)
        self._port: int = int(config.get(CONF_PORT, DEFAULT_PORT))
        self._comment: str = config.get(CONF_COMMENT, DEFAULT_COMMENT) or ""
        self._symbol_table: str = config.get(CONF_SYMBOL_TABLE, DEFAULT_SYMBOL_TABLE)
        self._symbol_code: str = config.get(CONF_SYMBOL_CODE, DEFAULT_SYMBOL_CODE)
        self._speed_unit: str = config.get(CONF_SPEED_UNIT, DEFAULT_SPEED_UNIT)
        if self._speed_unit not in _TO_KNOTS:
            self._speed_unit = DEFAULT_SPEED_UNIT
        self._min_distance_m: float = float(
            config.get(CONF_MIN_DISTANCE_M, DEFAULT_MIN_DISTANCE_M)
        )
        self._min_interval: timedelta = timedelta(
            seconds=int(config.get(CONF_MIN_INTERVAL_S, DEFAULT_MIN_INTERVAL_S))
        )
        self._max_interval: timedelta = timedelta(
            seconds=int(config.get(CONF_MAX_INTERVAL_S, DEFAULT_MAX_INTERVAL_S))
        )

        self._last_known: Fix | None = None
        self._last_sent: Position | None = None
        self._last_sent_at: datetime | None = None
        self._send_lock = asyncio.Lock()
        self._cancel_heartbeat: CALLBACK_TYPE | None = None
        self._stopped = False
        self._enabled = True
        self._send_speed_course = True
        self._send_altitude = True

    # ------------------------------------------------------------ properties

    @property
    def callsign(self) -> str:
        """Return the configured callsign."""
        return self._callsign

    @property
    def enabled(self) -> bool:
        """Return whether position reports are currently being sent."""
        return self._enabled

    @property
    def send_speed_course(self) -> bool:
        """Return whether speed and course are included in reports."""
        return self._send_speed_course

    @callback
    def set_send_speed_course(self, value: bool) -> None:
        """Include or omit speed and course in future reports."""
        self._send_speed_course = value

    @property
    def send_altitude(self) -> bool:
        """Return whether the altitude is included in reports."""
        return self._send_altitude

    @callback
    def set_send_altitude(self, value: bool) -> None:
        """Include or omit the altitude in future reports."""
        self._send_altitude = value

    async def async_set_enabled(self, enabled: bool) -> None:
        """Enable or disable beaconing.

        While disabled the tracker is still followed so the latest position
        is known, but nothing is sent. Re-enabling sends the last known
        position right away and restarts the heartbeat.
        """
        if enabled == self._enabled:
            return
        self._enabled = enabled
        if not enabled:
            _LOGGER.info("%s: beaconing disabled", self._callsign)
            self._cancel_timer()
            return
        _LOGGER.info("%s: beaconing enabled", self._callsign)
        if self._last_known is not None:
            await self._async_send(self._last_known, "beaconing re-enabled")
        else:
            self._schedule_heartbeat()

    # ------------------------------------------------------------- lifecycle

    async def async_start(self) -> None:
        """Register listeners and send the initial position if one is known."""
        self._entry.async_on_unload(
            async_track_state_change_event(
                self._hass, [self._entity_id], self._handle_state_event
            )
        )
        self._entry.async_on_unload(self._async_stop)

        initial = _fix_from_state(
            self._hass.states.get(self._entity_id), self._speed_unit
        )
        if initial is not None:
            self._last_known = initial
        if not self._enabled:
            _LOGGER.debug("%s: beaconing is disabled, not sending", self._callsign)
            return
        self._schedule_heartbeat()
        if initial is not None:
            await self._async_send(initial, "initial position")
        else:
            _LOGGER.debug(
                "%s: no position on %s yet, waiting for first fix",
                self._callsign,
                self._entity_id,
            )

    @callback
    def _async_stop(self) -> None:
        """Stop for good: cancel the heartbeat and prevent re-arming."""
        self._stopped = True
        self._cancel_timer()

    @callback
    def _cancel_timer(self) -> None:
        """Cancel the pending heartbeat timer, if any."""
        if self._cancel_heartbeat is not None:
            self._cancel_heartbeat()
            self._cancel_heartbeat = None

    # ---------------------------------------------------------------- events

    async def _handle_state_event(self, event: Event[EventStateChangedData]) -> None:
        """Evaluate a state change of the tracked entity."""
        fix = _fix_from_state(event.data["new_state"], self._speed_unit)
        if fix is None:
            _LOGGER.debug(
                "%s: %s changed without valid lat/lon, ignoring",
                self._callsign,
                self._entity_id,
            )
            return

        self._last_known = fix

        if not self._enabled:
            _LOGGER.debug("%s: beaconing disabled, position noted only", self._callsign)
            return

        if self._last_sent is None or self._last_sent_at is None:
            await self._async_send(fix, "first valid position")
            return

        distance = haversine_m(*self._last_sent, *fix.position)
        elapsed = dt_util.utcnow() - self._last_sent_at

        if distance < self._min_distance_m:
            _LOGGER.debug(
                "%s: moved %.1f m (< %.0f m), not sending",
                self._callsign,
                distance,
                self._min_distance_m,
            )
            return
        if elapsed < self._min_interval:
            _LOGGER.debug(
                "%s: moved %.1f m but only %.0f s since last report (< %.0f s), not sending",
                self._callsign,
                distance,
                elapsed.total_seconds(),
                self._min_interval.total_seconds(),
            )
            return

        await self._async_send(fix, f"moved {distance:.0f} m")

    async def _handle_heartbeat(self, _now: datetime) -> None:
        """Re-send the last known position once max_interval has elapsed."""
        self._cancel_heartbeat = None
        if not self._enabled:
            return
        try:
            if self._last_known is None:
                _LOGGER.debug("%s: heartbeat due but no position known", self._callsign)
                return
            if self._last_sent_at is not None:
                elapsed = dt_util.utcnow() - self._last_sent_at
                # Small tolerance for timer jitter.
                if elapsed < self._max_interval - timedelta(seconds=1):
                    return
            await self._async_send(self._last_known, "heartbeat")
        finally:
            # _async_send re-arms the timer itself; make sure one exists even
            # when we returned early above.
            if self._cancel_heartbeat is None:
                self._schedule_heartbeat()

    # --------------------------------------------------------------- sending

    @callback
    def _schedule_heartbeat(self) -> None:
        """(Re)arm the heartbeat timer for max_interval from now."""
        self._cancel_timer()
        if self._stopped or not self._enabled:
            return
        self._cancel_heartbeat = async_call_later(
            self._hass, self._max_interval, self._handle_heartbeat
        )

    async def async_send_now(self) -> None:
        """Send the last known position immediately, on user request.

        Ignores the distance/interval thresholds and the beaconing switch.
        Raises HomeAssistantError when no position is known or the send fails
        so the caller (e.g. a button press) can surface it in the UI.
        """
        if self._last_known is None:
            raise HomeAssistantError(
                f"{self._callsign}: no position known yet for {self._entity_id}"
            )
        if not await self._async_send(self._last_known, "manual", force=True):
            raise HomeAssistantError(
                f"{self._callsign}: sending to APRS-IS failed, see the log"
            )

    def _build_packet(self, fix: Fix) -> str:
        """Build the packet for a fix, honouring the include-switches."""
        return build_position_packet(
            self._callsign,
            fix.lat,
            fix.lon,
            self._symbol_table,
            self._symbol_code,
            self._comment,
            course=fix.course if self._send_speed_course else None,
            speed_kn=fix.speed_kn if self._send_speed_course else None,
            altitude_m=fix.altitude_m if self._send_altitude else None,
        )

    async def _async_send(self, fix: Fix, reason: str, *, force: bool = False) -> bool:
        """Build and transmit a position report; never raises.

        Returns True when the packet was handed to APRS-IS successfully.
        """
        if not self._enabled and not force:
            return False
        if self._send_lock.locked():
            _LOGGER.debug(
                "%s: send already in progress, skipping (%s)", self._callsign, reason
            )
            return False

        async with self._send_lock:
            packet = self._build_packet(fix)
            _LOGGER.debug("%s: sending (%s): %s", self._callsign, reason, packet)
            success = False
            try:
                await self._hass.async_add_executor_job(
                    send_packet,
                    self._callsign,
                    self._passcode,
                    self._host,
                    self._port,
                    packet,
                )
            except aprslib.exceptions.LoginError as err:
                _LOGGER.error(
                    "%s: APRS-IS rejected login at %s:%s: %s",
                    self._callsign,
                    self._host,
                    self._port,
                    err,
                )
            except (aprslib.exceptions.ConnectionError, OSError, TimeoutError) as err:
                _LOGGER.error(
                    "%s: could not reach APRS-IS at %s:%s: %s",
                    self._callsign,
                    self._host,
                    self._port,
                    err,
                )
            except Exception:  # noqa: BLE001  (aprslib must never take HA down)
                _LOGGER.exception(
                    "%s: unexpected error sending to APRS-IS", self._callsign
                )
            else:
                success = True
                self._last_sent = fix.position
                self._last_sent_at = dt_util.utcnow()
                _LOGGER.info(
                    "%s: position %.5f, %.5f sent to APRS-IS (%s)",
                    self._callsign,
                    fix.lat,
                    fix.lon,
                    reason,
                )
            finally:
                # Success or failure: refresh/retry after max_interval.
                self._schedule_heartbeat()
            return success
