"""Switch platform for Eques Smart Lock integration."""

import time
from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .client import EquesClient
from .const import CONF_DEVICE_NAME, CONF_DEVICE_UID, DEFAULT_QUEUE_TIMEOUT, DOMAIN


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Eques Queue Unlock Switch entity."""
    client: EquesClient = hass.data[DOMAIN][entry.entry_id]
    device_uid = entry.data[CONF_DEVICE_UID]
    device_name = entry.data.get(CONF_DEVICE_NAME, "Eques Smart Lock")

    switch_entity = EquesQueueUnlockSwitch(client, device_uid, device_name)
    async_add_entities([switch_entity])


class EquesQueueUnlockSwitch(SwitchEntity):
    """Switch to arm / disarm automatic unlock on the next doorbell ring."""

    _attr_has_entity_name = True
    _attr_translation_key = "unlock_on_ring"
    _attr_name = "Unlock on Doorbell Ring"
    _attr_icon = "mdi:door-open"

    def __init__(self, client: EquesClient, device_uid: str, device_name: str) -> None:
        self._client = client
        self._device_uid = device_uid
        self._device_name = device_name
        self._attr_unique_id = f"{device_uid}_queue_unlock_switch"

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, self._device_uid)},
            name=self._device_name,
            manufacturer="Eques",
            model="Smart Lock / Video Doorbell (Role 1015)",
        )

    @property
    def is_on(self) -> bool:
        now = time.time()
        return self._client.queue_enabled and now < self._client.queue_expires_at

    async def async_turn_on(self, **kwargs) -> None:
        """Arm the queue for 5 minutes."""
        self._client.arm_unlock_queue(DEFAULT_QUEUE_TIMEOUT)
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs) -> None:
        """Disarm the queue."""
        self._client.disarm_unlock_queue()
        self.async_write_ha_state()

    async def async_added_to_hass(self) -> None:
        self._client.register_callback(self.async_write_ha_state)

    async def async_will_remove_from_hass(self) -> None:
        self._client.remove_callback(self.async_write_ha_state)
