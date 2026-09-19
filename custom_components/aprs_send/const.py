"""Constants for the APRS Position Sender integration."""

from __future__ import annotations

from typing import Final

DOMAIN: Final = "aprs_send"

CONF_CALLSIGN: Final = "callsign"
CONF_PASSCODE: Final = "passcode"
CONF_ENTITY_ID: Final = "entity_id"
CONF_HOST: Final = "host"
CONF_PORT: Final = "port"
CONF_COMMENT: Final = "comment"
CONF_SYMBOL_TABLE: Final = "symbol_table"
CONF_SYMBOL_CODE: Final = "symbol_code"
CONF_MIN_DISTANCE_M: Final = "min_distance_m"
CONF_MIN_INTERVAL_S: Final = "min_interval_s"
CONF_MAX_INTERVAL_S: Final = "max_interval_s"

DEFAULT_HOST: Final = "rotate.aprs2.net"
DEFAULT_PORT: Final = 14580
DEFAULT_COMMENT: Final = "via HAtoAPRS"
DEFAULT_SYMBOL_TABLE: Final = "/"
DEFAULT_SYMBOL_CODE: Final = ">"
DEFAULT_MIN_DISTANCE_M: Final = 100
DEFAULT_MIN_INTERVAL_S: Final = 30
DEFAULT_MAX_INTERVAL_S: Final = 600

# APRS-IS destination address ("tocall") used in outgoing packets.
APRS_TOCALL: Final = "APRS"
# APRS spec limits the free-text comment of a position report to 43 characters.
MAX_COMMENT_LENGTH: Final = 43

# Unit of the tracker's "speed" attribute. Home Assistant's convention for
# device_tracker (e.g. the Companion app) is metres per second, but some
# integrations report km/h, knots or mph.
CONF_SPEED_UNIT: Final = "speed_unit"
SPEED_UNIT_MS: Final = "ms"
SPEED_UNIT_KMH: Final = "kmh"
SPEED_UNIT_KN: Final = "kn"
SPEED_UNIT_MPH: Final = "mph"
SPEED_UNITS: Final = [SPEED_UNIT_MS, SPEED_UNIT_KMH, SPEED_UNIT_KN, SPEED_UNIT_MPH]
DEFAULT_SPEED_UNIT: Final = SPEED_UNIT_MS

# Extra device_tracker attributes used for the optional packet fields.
ATTR_ALTITUDE: Final = "altitude"
ATTR_COURSE: Final = "course"
ATTR_SPEED: Final = "speed"
