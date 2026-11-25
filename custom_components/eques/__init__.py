"""Home Assistant Integration for Eques Smart Lock & Doorbell."""

import logging
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .client import EquesClient
from .const import (
    CONF_AUTO_RELOCK_SECONDS,
    CONF_DEVICE_UID,
    CONF_PASSWORD,
    CONF_PIN,
    CONF_QUEUE_TIMEOUT,
    CONF_USER_MAPPINGS,
    CONF_USERNAME,
    DEFAULT_AUTO_RELOCK_SECONDS,
    DEFAULT_QUEUE_TIMEOUT,
    DOMAIN,
    PLATFORMS,
)

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Eques Smart Lock from a config entry."""
    hass.data.setdefault(DOMAIN, {})

    username = entry.data[CONF_USERNAME]
    password = entry.data[CONF_PASSWORD]
    pin = entry.data[CONF_PIN]
    device_uid = entry.data[CONF_DEVICE_UID]

    # Combine data and options
    options = {**entry.data, **entry.options}
    auto_relock = options.get(CONF_AUTO_RELOCK_SECONDS, DEFAULT_AUTO_RELOCK_SECONDS)
    queue_timeout = options.get(CONF_QUEUE_TIMEOUT, DEFAULT_QUEUE_TIMEOUT)
    user_mappings = options.get(CONF_USER_MAPPINGS, {})

    client = EquesClient(
        username=username,
        password=password,
        pin=pin,
        device_uid=device_uid,
        auto_relock_seconds=auto_relock,
        queue_timeout=queue_timeout,
        user_mappings=user_mappings,
        cache_dir=hass.config.path(".storage"),
    )

    # Start persistent WebSocket connection in background
    await client.start()

    hass.data[DOMAIN][entry.entry_id] = client

    # Set up all platforms (lock, binary_sensor, sensor, switch)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Register options update listener
    entry.async_on_unload(entry.add_update_listener(async_update_options))

    return True


async def async_update_options(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Update options dynamically when changed in options flow."""
    client: EquesClient = hass.data[DOMAIN].get(entry.entry_id)
    if client:
        client.update_options(entry.options)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    client: EquesClient = hass.data[DOMAIN].get(entry.entry_id)
    if client:
        await client.stop()

    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)

    return unload_ok
