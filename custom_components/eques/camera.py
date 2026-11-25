"""Camera platform for Eques Smart Lock & Doorbell."""

import logging
from homeassistant.components.camera import Camera
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
    """Set up the Eques doorbell camera entity."""
    client: EquesClient = hass.data[DOMAIN][entry.entry_id]
    device_uid = entry.data[CONF_DEVICE_UID]
    device_name = entry.data.get(CONF_DEVICE_NAME, "Eques Smart Lock")

    camera_entity = EquesDoorbellCamera(client, device_uid, device_name)
    async_add_entities([camera_entity])


class EquesDoorbellCamera(Camera):
    """Representation of the Eques Doorbell snapshot camera."""

    _attr_has_entity_name = True
    _attr_translation_key = "camera"

    def __init__(self, client: EquesClient, device_uid: str, device_name: str) -> None:
        """Initialize the camera."""
        super().__init__()
        self._client = client
        self._device_uid = device_uid
        self._device_name = device_name
        self._attr_unique_id = f"{device_uid}_camera"

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
    def is_on(self) -> bool:
        """Return true if camera/cloud is online."""
        return self._client.connected_to_cloud

    @property
    def available(self) -> bool:
        """Return true if connected to cloud."""
        return self._client.connected_to_cloud

    @property
    def extra_state_attributes(self) -> dict:
        """Return device state attributes."""
        attrs = {}
        if self._client.last_snapshot_time:
            attrs["last_snapshot_time"] = self._client.last_snapshot_time
        if self._client.last_fid:
            attrs["last_fid"] = self._client.last_fid
        return attrs

    async def async_camera_image(
        self, width: int | None = None, height: int | None = None
    ) -> bytes | None:
        """Return bytes of the latest doorbell camera snapshot."""
        return self._client.last_snapshot_bytes

    async def async_added_to_hass(self) -> None:
        """Register state update callbacks."""
        self._client.register_callback(self.async_write_ha_state)

    async def async_will_remove_from_hass(self) -> None:
        """Unregister state update callbacks."""
        self._client.remove_callback(self.async_write_ha_state)
