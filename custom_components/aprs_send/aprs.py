"""Pure helpers for building and sending APRS position reports.

Everything in this module is synchronous and free of Home Assistant imports so
it can be unit-tested in isolation. The blocking network call must be executed
in an executor thread by the caller.
"""

from __future__ import annotations

import logging
import math
import re

import aprslib

from .const import APRS_TOCALL, MAX_COMMENT_LENGTH

_LOGGER = logging.getLogger(__name__)

# Base callsign of 1-6 alphanumerics, optional SSID 0-15 (APRS-IS also accepts
# two-character alphanumeric SSIDs, which we allow as well).
CALLSIGN_RE = re.compile(r"^[A-Z0-9]{1,6}(-[A-Z0-9]{1,2})?$")

EARTH_RADIUS_M = 6_371_000.0


def normalize_callsign(callsign: str) -> str:
    """Trim and upper-case a callsign."""
    return callsign.strip().upper()


def is_valid_callsign(callsign: str) -> bool:
    """Return True if the callsign (with optional SSID) looks well-formed."""
    return CALLSIGN_RE.match(callsign) is not None


def passcode_matches(callsign: str, passcode: str) -> bool:
    """Check the APRS-IS passcode against the value derived from the callsign."""
    try:
        given = int(passcode.strip())
    except (TypeError, ValueError):
        return False
    base = callsign.split("-", 1)[0]
    return given == aprslib.passcode(base)


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance between two WGS84 points in metres."""
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lon2 - lon1)
    a = (
        math.sin(d_phi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    )
    return 2 * EARTH_RADIUS_M * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _split_degrees(value: float) -> tuple[int, float]:
    """Split an absolute decimal degree value into degrees and hundredth-minutes.

    Minutes are rounded to two decimals first; a carry into the next full
    degree is handled so that 59.999 minutes never renders as "60.00".
    """
    degrees = int(value)
    minutes = round((value - degrees) * 60, 2)
    if minutes >= 60.0:
        degrees += 1
        minutes = 0.0
    return degrees, minutes


def format_latitude(lat: float) -> str:
    """Format latitude as DDMM.hhN / DDMM.hhS."""
    hemisphere = "N" if lat >= 0 else "S"
    degrees, minutes = _split_degrees(abs(lat))
    return f"{degrees:02d}{minutes:05.2f}{hemisphere}"


def format_longitude(lon: float) -> str:
    """Format longitude as DDDMM.hhE / DDDMM.hhW."""
    hemisphere = "E" if lon >= 0 else "W"
    degrees, minutes = _split_degrees(abs(lon))
    return f"{degrees:03d}{minutes:05.2f}{hemisphere}"


def _course_speed_extension(course: float | None, speed_kn: float | None) -> str:
    """Return the 7-byte CSE/SPD data extension, or "" if no speed is known.

    Course is 001-360 degrees (000 = unknown), speed is whole knots 000-999.
    """
    if speed_kn is None:
        return ""
    if course is None:
        cse = 0
    else:
        cse = int(round(course)) % 360
        if cse == 0:
            cse = 360
    spd = max(0, min(999, int(round(speed_kn))))
    return f"{cse:03d}/{spd:03d}"


def _altitude_field(altitude_m: float | None) -> str:
    """Return the "/A=nnnnnn" altitude field (feet), or "" if unknown."""
    if altitude_m is None:
        return ""
    feet = int(round(altitude_m / 0.3048))
    feet = max(-99999, min(999999, feet))
    return f"/A={feet:06d}"


def build_position_packet(
    callsign: str,
    lat: float,
    lon: float,
    symbol_table: str,
    symbol_code: str,
    comment: str = "",
    *,
    course: float | None = None,
    speed_kn: float | None = None,
    altitude_m: float | None = None,
) -> str:
    """Build an uncompressed APRS position report without timestamp/messaging.

    Optional course/speed go into the data extension right after the symbol,
    the altitude into the comment as "/A=nnnnnn" (feet). The free-text
    comment is truncated so that altitude field plus text fit the APRS limit.
    """
    altitude = _altitude_field(altitude_m)
    clean_comment = comment.strip()[: MAX_COMMENT_LENGTH - len(altitude)]
    return (
        f"{callsign}>{APRS_TOCALL},TCPIP*:!"
        f"{format_latitude(lat)}{symbol_table}"
        f"{format_longitude(lon)}{symbol_code}"
        f"{_course_speed_extension(course, speed_kn)}"
        f"{altitude}{clean_comment}"
    )


def send_packet(
    callsign: str, passcode: str, host: str, port: int, packet: str
) -> None:
    """Open an APRS-IS connection, send one packet and close again.

    Blocking. Raises aprslib.exceptions.LoginError on bad credentials and
    aprslib.exceptions.ConnectionError / OSError on network problems.
    """
    ais = aprslib.IS(callsign, passwd=passcode, host=host, port=port)
    ais.connect()
    try:
        ais.sendall(packet)
    finally:
        ais.close()


def test_connection(callsign: str, passcode: str, host: str, port: int) -> None:
    """Log in to APRS-IS once to verify credentials and reachability.

    Blocking. Raises the same exceptions as send_packet.
    """
    ais = aprslib.IS(callsign, passwd=passcode, host=host, port=port)
    ais.connect()
    ais.close()
