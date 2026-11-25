"""Button platform for Eques Smart Lock & Doorbell."""

import logging
from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
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
    """Set up the Eques button entity."""
    client: EquesClient = hass.data[DOMAIN][entry.entry_id]
    device_uid = entry.data[CONF_DEVICE_UID]
    device_name = entry.data.get(CONF_DEVICE_NAME, "Eques Smart Lock")

    entities = [
        EquesWakeCameraButton(client, device_uid, device_name),
    ]
    async_add_entities(entities)


class EquesWakeCameraButton(ButtonEntity):
    """Button to wake up the doorbell camera and request video stream."""

    _attr_has_entity_name = True
    _attr_translation_key = "wake_camera"
    _attr_icon = "mdi:camera-wireless"

    def __init__(self, client: EquesClient, device_uid: str, device_name: str) -> None:
        """Initialize the button entity."""
        super().__init__()
        self._client = client
        self._device_uid = device_uid
        self._device_name = device_name
        self._attr_unique_id = f"{device_uid}_wake_camera"

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
    def available(self) -> bool:
        """Return true if connected to cloud."""
        return self._client.connected_to_cloud

    async def async_press(self) -> None:
        """Handle button press to wake the camera / open monitor mode."""
        _LOGGER.info("Wake camera button pressed for %s", self._device_uid)
        await self._client.async_wake_camera()
