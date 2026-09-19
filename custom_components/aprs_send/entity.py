"""Shared entity helpers."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo

from .const import DOMAIN
from .sender import AprsPositionSender


def aprs_device_info(entry: ConfigEntry, sender: AprsPositionSender) -> DeviceInfo:
    """Return the device all entities of one config entry attach to."""
    return DeviceInfo(
        identifiers={(DOMAIN, entry.entry_id)},
        name=f"APRS {sender.callsign}",
        manufacturer="APRS-IS",
        model="Position Sender",
        entry_type=DeviceEntryType.SERVICE,
    )
