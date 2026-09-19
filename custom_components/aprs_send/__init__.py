"""The APRS Position Sender integration."""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .const import DOMAIN
from .sender import AprsPositionSender

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.BUTTON, Platform.SWITCH]

type AprsSendConfigEntry = ConfigEntry[AprsPositionSender]


async def async_setup_entry(hass: HomeAssistant, entry: AprsSendConfigEntry) -> bool:
    """Set up APRS Position Sender from a config entry."""
    sender = AprsPositionSender(hass, entry)
    entry.runtime_data = sender

    # Platforms first: the switch restores its previous on/off state during
    # setup, so a sender that was switched off before a restart stays off and
    # does not beacon once at startup.
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # All listeners/timers created by the sender are registered via
    # entry.async_on_unload, so unloading the entry tears them down.
    await sender.async_start()

    # Reload the entry whenever the options are changed.
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))

    _LOGGER.debug("%s: set up for %s", DOMAIN, entry.title)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: AprsSendConfigEntry) -> bool:
    """Unload a config entry."""
    _LOGGER.debug("%s: unloading %s", DOMAIN, entry.title)
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def _async_update_listener(hass: HomeAssistant, entry: AprsSendConfigEntry) -> None:
    """Handle options update by reloading the entry."""
    await hass.config_entries.async_reload(entry.entry_id)
