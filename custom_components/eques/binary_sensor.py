"""Binary sensor platform for Eques integration."""

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
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
    """Set up Eques binary sensor entities."""
    client: EquesClient = hass.data[DOMAIN][entry.entry_id]
    device_uid = entry.data[CONF_DEVICE_UID]
    device_name = entry.data.get(CONF_DEVICE_NAME, "Eques Smart Lock")

    entities = [
        EquesDoorbellBinarySensor(client, device_uid, device_name),
        EquesCloudStatusBinarySensor(client, device_uid, device_name),
    ]
    async_add_entities(entities)


class EquesBaseBinarySensor(BinarySensorEntity):
    """Base class for Eques binary sensors."""

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


class EquesDoorbellBinarySensor(EquesBaseBinarySensor):
    """Binary sensor indicating if doorbell is actively ringing."""

    _attr_translation_key = "doorbell"
    _attr_name = "Doorbell"
    _attr_device_class = BinarySensorDeviceClass.OCCUPANCY
    _attr_icon = "mdi:bell-ring"

    def __init__(self, client: EquesClient, device_uid: str, device_name: str) -> None:
        super().__init__(client, device_uid, device_name)
        self._attr_unique_id = f"{device_uid}_doorbell_ringing"

    @property
    def is_on(self) -> bool:
        return self._client.is_doorbell_ringing


class EquesCloudStatusBinarySensor(EquesBaseBinarySensor):
    """Binary sensor indicating if connection to Eques Cloud is active."""

    _attr_translation_key = "cloud_connected"
    _attr_name = "Cloud Connection"
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY

    def __init__(self, client: EquesClient, device_uid: str, device_name: str) -> None:
        super().__init__(client, device_uid, device_name)
        self._attr_unique_id = f"{device_uid}_cloud_connected"

    @property
    def is_on(self) -> bool:
        return self._client.connected_to_cloud
