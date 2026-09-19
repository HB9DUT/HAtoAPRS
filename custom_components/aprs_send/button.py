"""Button to send the current position to APRS-IS immediately."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .entity import aprs_device_info
from .sender import AprsPositionSender


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the send-now button for a config entry."""
    sender: AprsPositionSender = entry.runtime_data
    async_add_entities([AprsSendNowButton(entry, sender)])


class AprsSendNowButton(ButtonEntity):
    """Send the last known position right away, ignoring all thresholds."""

    _attr_has_entity_name = True
    _attr_translation_key = "send_now"
    _attr_icon = "mdi:send"

    def __init__(self, entry: ConfigEntry, sender: AprsPositionSender) -> None:
        """Initialise the button."""
        self._sender = sender
        self._attr_unique_id = f"{entry.entry_id}_send_now"
        self._attr_device_info = aprs_device_info(entry, sender)

    async def async_press(self) -> None:
        """Send now. Errors propagate so the UI shows them."""
        await self._sender.async_send_now()
