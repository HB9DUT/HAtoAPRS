"""Switches controlling what the APRS position sender transmits."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.switch import SwitchEntity, SwitchEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import STATE_OFF
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from .entity import aprs_device_info
from .sender import AprsPositionSender


@dataclass(frozen=True, kw_only=True)
class AprsSwitchDescription(SwitchEntityDescription):
    """Describe a switch backed by a flag on the sender."""

    is_on_fn: Callable[[AprsPositionSender], bool]
    set_fn: Callable[[AprsPositionSender, bool], Awaitable[None] | None]


async def _set_enabled(sender: AprsPositionSender, value: bool) -> None:
    await sender.async_set_enabled(value)


SWITCHES: tuple[AprsSwitchDescription, ...] = (
    AprsSwitchDescription(
        key="beaconing",
        translation_key="beaconing",
        icon="mdi:radio-tower",
        is_on_fn=lambda s: s.enabled,
        set_fn=_set_enabled,
    ),
    AprsSwitchDescription(
        key="send_speed_course",
        translation_key="send_speed_course",
        icon="mdi:speedometer",
        entity_category=EntityCategory.CONFIG,
        is_on_fn=lambda s: s.send_speed_course,
        set_fn=lambda s, v: s.set_send_speed_course(v),
    ),
    AprsSwitchDescription(
        key="send_altitude",
        translation_key="send_altitude",
        icon="mdi:altimeter",
        entity_category=EntityCategory.CONFIG,
        is_on_fn=lambda s: s.send_altitude,
        set_fn=lambda s, v: s.set_send_altitude(v),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the switches for a config entry."""
    sender: AprsPositionSender = entry.runtime_data
    async_add_entities(AprsSwitch(entry, sender, desc) for desc in SWITCHES)


class AprsSwitch(RestoreEntity, SwitchEntity):
    """A switch that toggles one flag of the sender and restores its state."""

    entity_description: AprsSwitchDescription
    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(
        self,
        entry: ConfigEntry,
        sender: AprsPositionSender,
        description: AprsSwitchDescription,
    ) -> None:
        """Initialise the switch."""
        self.entity_description = description
        self._sender = sender
        self._attr_unique_id = f"{entry.entry_id}_{description.key}"
        self._attr_device_info = aprs_device_info(entry, sender)

    async def async_added_to_hass(self) -> None:
        """Restore the previous on/off state before the sender starts."""
        await super().async_added_to_hass()
        last_state = await self.async_get_last_state()
        if last_state is not None and last_state.state == STATE_OFF:
            await self._async_apply(False)

    async def _async_apply(self, value: bool) -> None:
        result = self.entity_description.set_fn(self._sender, value)
        if result is not None:
            await result

    @property
    def is_on(self) -> bool:
        """Return the current flag value."""
        return self.entity_description.is_on_fn(self._sender)

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the flag on."""
        await self._async_apply(True)
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the flag off."""
        await self._async_apply(False)
        self.async_write_ha_state()
