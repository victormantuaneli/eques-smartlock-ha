"""Camera platform for Eques Smart Lock & Doorbell."""

import logging
from homeassistant.components.camera import Camera, CameraEntityFeature
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
    """Representation of the Eques Doorbell camera (snapshots and live RTSP stream)."""

    _attr_has_entity_name = True
    _attr_translation_key = "camera"
    _attr_supported_features = CameraEntityFeature.STREAM

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
        if self._client.camera_rtsp_url:
            attrs["stream_url"] = self._client.camera_rtsp_url
        if self._client.device_ip:
            attrs["device_ip"] = self._client.device_ip
        return attrs

    async def stream_source(self) -> str | None:
        """Return the RTSP stream source for live view."""
        if self._client.camera_rtsp_url:
            return self._client.camera_rtsp_url

        # Trigger wake-up command and SSDP discovery if stream requested
        await self._client.async_wake_camera()
        return self._client.camera_rtsp_url

    async def async_camera_image(
        self, width: int | None = None, height: int | None = None
    ) -> bytes | None:
        """Return bytes of the latest doorbell camera snapshot, rotated to correct orientation."""
        data = self._client.last_snapshot_bytes
        if not data:
            return None

        rotation = getattr(self._client, "camera_rotation", 90)
        if rotation % 360 == 0:
            return data

        return await self.hass.async_add_executor_job(
            self._rotate_image, data, rotation
        )

    def _rotate_image(self, data: bytes, degrees: int) -> bytes:
        """Rotates image bytes using Pillow in worker thread."""
        try:
            from PIL import Image
            import io

            img = Image.open(io.BytesIO(data))
            rotated = img.rotate(degrees, expand=True)
            out = io.BytesIO()
            rotated.save(out, format="JPEG", quality=92)
            return out.getvalue()
        except Exception as err:
            _LOGGER.warning("Could not rotate snapshot image: %s", err)
            return data

    async def async_added_to_hass(self) -> None:
        """Register state update callbacks."""
        self._client.register_callback(self.async_write_ha_state)

    async def async_will_remove_from_hass(self) -> None:
        """Unregister state update callbacks."""
        self._client.remove_callback(self.async_write_ha_state)
