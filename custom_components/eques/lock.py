"""Lock platform for Eques Smart Lock integration."""

import logging
from homeassistant.components.lock import LockEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .client import EquesClient
from .const import CONF_DEVICE_NAME, CONF_DEVICE_UID, DOMAIN

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Eques Lock entity."""
    client: EquesClient = hass.data[DOMAIN][entry.entry_id]
    device_uid = entry.data[CONF_DEVICE_UID]
    device_name = entry.data.get(CONF_DEVICE_NAME, "Eques Smart Lock")

    lock_entity = EquesLockEntity(client, device_uid, device_name)
    async_add_entities([lock_entity])


class EquesLockEntity(LockEntity):
    """Representation of an Eques Smart Lock."""

    _attr_has_entity_name = True
    _attr_translation_key = "lock"
    _attr_name = None

    def __init__(self, client: EquesClient, device_uid: str, device_name: str) -> None:
        self._client = client
        self._device_uid = device_uid
        self._device_name = device_name
        self._attr_unique_id = f"{device_uid}_lock"

    @property
    def device_info(self) -> DeviceInfo:
        """Return device registry information."""
        return DeviceInfo(
            identifiers={(DOMAIN, self._device_uid)},
            name=self._device_name,
            manufacturer="Eques",
            model="Smart Lock / Video Doorbell (Role 1015)",
        )

    @property
    def is_locked(self) -> bool:
        """Return true if lock is locked."""
        return self._client.is_locked

    @property
    def available(self) -> bool:
        """Return true if connected to cloud."""
        return self._client.connected_to_cloud

    async def async_unlock(self, **kwargs) -> None:
        """Unlock the smart lock."""
        code = kwargs.get("code")
        _LOGGER.info("Unlocking Eques Smart Lock...")
        await self._client.async_unlock(pin=code, arm_if_sleeping=True)

    async def async_lock(self, **kwargs) -> None:
        """Eques locks mechanically relock automatically; this manually forces locked state."""
        self._client.is_locked = True
        self.async_write_ha_state()

    async def async_added_to_hass(self) -> None:
        """Register client update callback."""
        self._client.register_callback(self.async_write_ha_state)

    async def async_will_remove_from_hass(self) -> None:
        """Remove client update callback."""
        self._client.remove_callback(self.async_write_ha_state)
