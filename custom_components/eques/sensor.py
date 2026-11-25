"""Sensor platform for Eques Smart Lock integration."""

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .client import EquesClient
from .const import CONF_DEVICE_NAME, CONF_DEVICE_UID, DOMAIN


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Eques sensors."""
    client: EquesClient = hass.data[DOMAIN][entry.entry_id]
    device_uid = entry.data[CONF_DEVICE_UID]
    device_name = entry.data.get(CONF_DEVICE_NAME, "Eques Smart Lock")

    entities = [
        EquesLastUnlockMethodSensor(client, device_uid, device_name),
        EquesLastUnlockUserSensor(client, device_uid, device_name),
        EquesLastUnlockTimeSensor(client, device_uid, device_name),
        EquesLastRingTimeSensor(client, device_uid, device_name),
        EquesDeviceStatusSensor(client, device_uid, device_name),
    ]
    async_add_entities(entities)


class EquesBaseSensor(SensorEntity):
    """Base sensor for Eques entities."""

    _attr_has_entity_name = True

    def __init__(self, client: EquesClient, device_uid: str, device_name: str) -> None:
        self._client = client
        self._device_uid = device_uid
        self._device_name = device_name

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, self._device_uid)},
            name=self._device_name,
            manufacturer="Eques",
            model="Smart Lock / Video Doorbell (Role 1015)",
        )

    async def async_added_to_hass(self) -> None:
        self._client.register_callback(self.async_write_ha_state)

    async def async_will_remove_from_hass(self) -> None:
        self._client.remove_callback(self.async_write_ha_state)


class EquesLastUnlockMethodSensor(EquesBaseSensor):
    """Sensor reporting the method used for the last unlock."""

    _attr_translation_key = "last_unlock_method"
    _attr_name = "Last Unlock Method"
    _attr_icon = "mdi:lock-open-variant"

    def __init__(self, client: EquesClient, device_uid: str, device_name: str) -> None:
        super().__init__(client, device_uid, device_name)
        self._attr_unique_id = f"{device_uid}_last_unlock_method"

    @property
    def native_value(self) -> str | None:
        return self._client.last_unlock_type


class EquesLastUnlockUserSensor(EquesBaseSensor):
    """Sensor reporting the nickname or ID of who unlocked."""

    _attr_translation_key = "last_unlock_user"
    _attr_name = "Last Unlock User"
    _attr_icon = "mdi:account-key"

    def __init__(self, client: EquesClient, device_uid: str, device_name: str) -> None:
        super().__init__(client, device_uid, device_name)
        self._attr_unique_id = f"{device_uid}_last_unlock_user"

    @property
    def native_value(self) -> str | None:
        return self._client.last_unlock_nick or self._client.last_unlock_user


class EquesLastUnlockTimeSensor(EquesBaseSensor):
    """Sensor reporting timestamp of last unlock."""

    _attr_translation_key = "last_unlock_time"
    _attr_name = "Last Unlock Time"
    _attr_icon = "mdi:clock-time-four-outline"

    def __init__(self, client: EquesClient, device_uid: str, device_name: str) -> None:
        super().__init__(client, device_uid, device_name)
        self._attr_unique_id = f"{device_uid}_last_unlock_datetime"

    @property
    def native_value(self) -> str | None:
        return self._client.last_unlock_datetime


class EquesLastRingTimeSensor(EquesBaseSensor):
    """Sensor reporting timestamp of last doorbell ring."""

    _attr_translation_key = "last_ring_time"
    _attr_name = "Last Doorbell Ring Time"
    _attr_icon = "mdi:bell-badge-outline"

    def __init__(self, client: EquesClient, device_uid: str, device_name: str) -> None:
        super().__init__(client, device_uid, device_name)
        self._attr_unique_id = f"{device_uid}_last_ring_datetime"

    @property
    def native_value(self) -> str | None:
        return self._client.last_ring_datetime


class EquesDeviceStatusSensor(EquesBaseSensor):
    """Sensor reporting device power / communication status."""

    _attr_translation_key = "device_status"
    _attr_name = "Device Status"
    _attr_icon = "mdi:power-sleep"

    def __init__(self, client: EquesClient, device_uid: str, device_name: str) -> None:
        super().__init__(client, device_uid, device_name)
        self._attr_unique_id = f"{device_uid}_device_status"

    @property
    def native_value(self) -> str:
        return self._client.device_status
