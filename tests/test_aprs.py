"""Tests for the pure APRS helpers."""

from __future__ import annotations

import aprslib
import pytest

from custom_components.aprs_send import aprs


@pytest.mark.parametrize(
    ("lat", "expected"),
    [
        (46.9481, "4656.89N"),
        (-33.8688, "3352.13S"),
        (0, "0000.00N"),
        (46.999999, "4700.00N"),  # minute carry
    ],
)
def test_format_latitude(lat: float, expected: str) -> None:
    assert aprs.format_latitude(lat) == expected


@pytest.mark.parametrize(
    ("lon", "expected"),
    [
        (7.4474, "00726.84E"),
        (-118.2437, "11814.62W"),
        (179.999999, "18000.00E"),
    ],
)
def test_format_longitude(lon: float, expected: str) -> None:
    assert aprs.format_longitude(lon) == expected


def test_haversine() -> None:
    assert 94_000 < aprs.haversine_m(46.9481, 7.4474, 47.3769, 8.5417) < 96_000
    assert aprs.haversine_m(46.0, 7.0, 46.0, 7.0) == 0.0


def test_basic_packet() -> None:
    packet = aprs.build_position_packet("HB9XX-9", 46.9481, 7.4474, "/", ">", " hi ")
    assert packet == "HB9XX-9>APRS,TCPIP*:!4656.89N/00726.84E>hi"


def test_packet_with_course_speed_altitude_round_trips() -> None:
    packet = aprs.build_position_packet(
        "HB9XX-9",
        46.9481,
        7.4474,
        "/",
        ">",
        "test",
        course=87.6,
        speed_kn=45.4,
        altitude_m=540.0,
    )
    assert packet == "HB9XX-9>APRS,TCPIP*:!4656.89N/00726.84E>088/045/A=001772test"

    parsed = aprslib.parse(packet)
    assert parsed["course"] == 88
    assert parsed["speed"] == pytest.approx(45 * 1.852, abs=0.01)  # km/h
    assert parsed["altitude"] == pytest.approx(540, abs=0.5)  # metres
    assert parsed["comment"] == "test"


def test_speed_without_course_uses_000() -> None:
    packet = aprs.build_position_packet(
        "HB9XX-9", 46.9481, 7.4474, "/", ">", "", speed_kn=12
    )
    assert packet.endswith("E>000/012")


def test_course_zero_becomes_360_and_speed_is_clamped() -> None:
    packet = aprs.build_position_packet(
        "HB9XX-9", 46.9481, 7.4474, "/", ">", "", course=0, speed_kn=1500
    )
    assert packet.endswith("E>360/999")


def test_course_without_speed_is_omitted() -> None:
    packet = aprs.build_position_packet(
        "HB9XX-9", 46.9481, 7.4474, "/", ">", "x", course=90
    )
    assert packet.endswith("E>x")


def test_negative_altitude() -> None:
    packet = aprs.build_position_packet(
        "HB9XX-9", 46.9481, 7.4474, "/", ">", "", altitude_m=-30.48
    )
    assert packet.endswith("E>/A=-00100")
    assert aprslib.parse(packet)["altitude"] == pytest.approx(-30.48, abs=0.01)


def test_altitude_counts_against_comment_limit() -> None:
    packet = aprs.build_position_packet(
        "HB9XX-9", 46.9481, 7.4474, "/", ">", "x" * 60, altitude_m=100
    )
    tail = packet.split("E>", 1)[1]
    assert tail.startswith("/A=000328")
    assert len(tail) == 43


@pytest.mark.parametrize(
    ("callsign", "valid"),
    [
        ("HB9XX-9", True),
        ("N0CALL", True),
        ("HB9XX-15", True),
        ("HB9XX-", False),
        ("TOOLONGCALL", False),
        ("hb9xx", False),
    ],
)
def test_is_valid_callsign(callsign: str, valid: bool) -> None:
    assert aprs.is_valid_callsign(callsign) is valid


def test_passcode_matches() -> None:
    assert aprs.passcode_matches("N0CALL-9", "13023")
    assert aprs.passcode_matches("N0CALL", " 13023 ")
    assert not aprs.passcode_matches("N0CALL", "12345")
    assert not aprs.passcode_matches("N0CALL", "abc")
