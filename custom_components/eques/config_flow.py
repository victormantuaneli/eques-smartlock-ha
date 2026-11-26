"""Config flow for Eques Smart Lock & Doorbell integration."""

import hashlib
import json
import logging
from aiohttp import ClientSession, WSMsgType
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import callback

from .const import (
    APP_ID,
    APP_KEY,
    CLOUD_HOST,
    CLOUD_WS_URL,
    CONF_AUTO_RELOCK_SECONDS,
    CONF_DEVICE_NAME,
    CONF_DEVICE_UID,
    CONF_PASSWORD,
    CONF_PIN,
    CONF_QUEUE_TIMEOUT,
    CONF_USER_MAPPINGS,
    CONF_USERNAME,
    CONF_CAMERA_ROTATION,
    DEFAULT_AUTO_RELOCK_SECONDS,
    DEFAULT_QUEUE_TIMEOUT,
    DEFAULT_CAMERA_ROTATION,
    ROTATION_OPTIONS,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)


async def validate_credentials_and_get_devices(username, password):
    """Connects to Eques Cloud to validate login and retrieve device list."""
    password_md5 = hashlib.md5(password.encode("utf-8")).hexdigest()
    login_payload = {
        "method": "login_v2",
        "name_stype": "uname",
        "name": username,
        "token_stype": "passwd_md5",
        "token": password_md5,
        "app_key": APP_KEY,
        "app_id": APP_ID,
    }

    devices = []
    try:
        async with ClientSession() as session:
            async with session.ws_connect(CLOUD_WS_URL, timeout=10) as ws:
                await ws.send_str(json.dumps(login_payload))
                async for msg in ws:
                    if msg.type == WSMsgType.TEXT:
                        payload = json.loads(msg.data)
                        method = payload.get("method")
                        code = payload.get("code")

                        if method == "login_v2":
                            if code != 4000:
                                return False, "invalid_auth", []
                            # Request device list
                            await ws.send_str(json.dumps({"method": "bdylist"}))

                        elif method == "bdylist":
                            bdy_list = payload.get("bdylist", [])
                            for dev in bdy_list:
                                devices.append({
                                    "uid": dev.get("bid"),
                                    "name": dev.get("name") or dev.get("defaultNick", "Eques Lock"),
                                    "role": dev.get("role"),
                                })
                            await ws.close()
                            return True, None, devices
    except Exception as err:
        _LOGGER.error("Failed to connect to Eques cloud: %s", err)
        return False, "cannot_connect", []

    return False, "cannot_connect", []


class EquesConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Eques Smart Lock & Doorbell."""

    VERSION = 1

    def __init__(self):
        self._user_inputs = {}
        self._devices = []

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        """Get the options flow for this handler."""
        return EquesOptionsFlowHandler(config_entry)

    async def async_step_user(self, user_input=None):
        """Handle the initial step where user provides credentials and unlock PIN."""
        errors = {}

        if user_input is not None:
            username = user_input[CONF_USERNAME].strip()
            password = user_input[CONF_PASSWORD].strip()
            pin = user_input[CONF_PIN].strip()

            success, error_reason, devices = await validate_credentials_and_get_devices(
                username, password
            )

            if not success:
                errors["base"] = error_reason or "invalid_auth"
            elif not devices:
                errors["base"] = "no_devices_found"
            else:
                self._user_inputs = {
                    CONF_USERNAME: username,
                    CONF_PASSWORD: password,
                    CONF_PIN: pin,
                }
                self._devices = devices

                # If only one device, auto-select it
                if len(devices) == 1:
                    dev = devices[0]
                    await self.async_set_unique_id(dev["uid"])
                    self._abort_if_unique_id_configured()

                    return self.async_create_entry(
                        title=f"{dev['name']} ({username})",
                        data={
                            **self._user_inputs,
                            CONF_DEVICE_UID: dev["uid"],
                            CONF_DEVICE_NAME: dev["name"],
                            CONF_AUTO_RELOCK_SECONDS: DEFAULT_AUTO_RELOCK_SECONDS,
                            CONF_QUEUE_TIMEOUT: DEFAULT_QUEUE_TIMEOUT,
                            CONF_USER_MAPPINGS: {},
                        },
                    )

                return await self.async_step_device()

        data_schema = vol.Schema({
            vol.Required(CONF_USERNAME): str,
            vol.Required(CONF_PASSWORD): str,
            vol.Required(CONF_PIN): str,
        })

        return self.async_show_form(
            step_id="user",
            data_schema=data_schema,
            errors=errors,
        )

    async def async_step_device(self, user_input=None):
        """Step to select device if user has multiple devices."""
        if user_input is not None:
            selected_uid = user_input[CONF_DEVICE_UID]
            dev = next((d for d in self._devices if d["uid"] == selected_uid), None)
            dev_name = dev["name"] if dev else "Eques Lock"

            await self.async_set_unique_id(selected_uid)
            self._abort_if_unique_id_configured()

            return self.async_create_entry(
                title=f"{dev_name} ({self._user_inputs[CONF_USERNAME]})",
                data={
                    **self._user_inputs,
                    CONF_DEVICE_UID: selected_uid,
                    CONF_DEVICE_NAME: dev_name,
                    CONF_AUTO_RELOCK_SECONDS: DEFAULT_AUTO_RELOCK_SECONDS,
                    CONF_QUEUE_TIMEOUT: DEFAULT_QUEUE_TIMEOUT,
                    CONF_USER_MAPPINGS: {},
                },
            )

        device_options = {d["uid"]: f"{d['name']} ({d['uid'][:8]}...)" for d in self._devices}
        data_schema = vol.Schema({
            vol.Required(CONF_DEVICE_UID): vol.In(device_options),
        })

        return self.async_show_form(
            step_id="device",
            data_schema=data_schema,
        )


class EquesOptionsFlowHandler(config_entries.OptionsFlow):
    """Handle options flow for Eques integration (modal de usuários e configurações)."""

    def __init__(self, config_entry: config_entries.ConfigEntry | None = None) -> None:
        self._config_entry_override = config_entry

    def _get_entry(self) -> config_entries.ConfigEntry:
        """Get config entry safely without property collision."""
        try:
            entry = super().config_entry
            if entry is not None:
                return entry
        except Exception:
            pass
        if self._config_entry_override is not None:
            return self._config_entry_override
        if hasattr(self, "handler") and self.handler and self.hass:
            return self.hass.config_entries.async_get_entry(self.handler)
        return None

    async def async_step_init(self, user_input=None):
        """Manage Eques options (friendly user mapping and timeouts)."""
        entry = self._get_entry()
        current_options = {}
        if entry is not None:
            current_options = {**entry.data, **entry.options}
        current_mappings = current_options.get(CONF_USER_MAPPINGS) or {}

        if user_input is not None:
            # Build user mapping dictionary from form inputs
            new_mappings = {}
            for i in range(1, 10):
                key = f"user_{i}"
                val = user_input.get(key)
                if val and isinstance(val, str) and val.strip():
                    new_mappings[str(i)] = val.strip()

            # Parse custom mappings textarea (lines formatted as "ID: Nome")
            custom_lines = user_input.get("custom_users") or ""
            for line in str(custom_lines).splitlines():
                if ":" in line:
                    uid_part, name_part = line.split(":", 1)
                    uid_clean = uid_part.strip()
                    name_clean = name_part.strip()
                    if uid_clean and name_clean:
                        new_mappings[uid_clean] = name_clean

            options_data = {
                CONF_USER_MAPPINGS: new_mappings,
                CONF_AUTO_RELOCK_SECONDS: user_input.get(
                    CONF_AUTO_RELOCK_SECONDS, DEFAULT_AUTO_RELOCK_SECONDS
                ),
                CONF_QUEUE_TIMEOUT: user_input.get(
                    CONF_QUEUE_TIMEOUT, DEFAULT_QUEUE_TIMEOUT
                ),
                CONF_CAMERA_ROTATION: user_input.get(
                    CONF_CAMERA_ROTATION, DEFAULT_CAMERA_ROTATION
                ),
            }

            return self.async_create_entry(title="", data=options_data)

        # Pre-fill custom lines for any IDs not 1..5
        custom_lines_list = []
        for uid, name in current_mappings.items():
            if uid not in [str(i) for i in range(1, 10)]:
                custom_lines_list.append(f"{uid}: {name}")

        schema = vol.Schema({
            vol.Optional("user_1", default=current_mappings.get("1", "")): vol.Any(None, str),
            vol.Optional("user_2", default=current_mappings.get("2", "")): vol.Any(None, str),
            vol.Optional("user_3", default=current_mappings.get("3", "")): vol.Any(None, str),
            vol.Optional("user_4", default=current_mappings.get("4", "")): vol.Any(None, str),
            vol.Optional("user_5", default=current_mappings.get("5", "")): vol.Any(None, str),
            vol.Optional("custom_users", default="\n".join(custom_lines_list)): vol.Any(None, str),
            vol.Optional(
                CONF_AUTO_RELOCK_SECONDS,
                default=current_options.get(
                    CONF_AUTO_RELOCK_SECONDS, DEFAULT_AUTO_RELOCK_SECONDS
                ),
            ): vol.All(vol.Coerce(int), vol.Range(min=3, max=120)),
            vol.Optional(
                CONF_QUEUE_TIMEOUT,
                default=current_options.get(
                    CONF_QUEUE_TIMEOUT, DEFAULT_QUEUE_TIMEOUT
                ),
            ): vol.All(vol.Coerce(int), vol.Range(min=30, max=1800)),
            vol.Optional(
                CONF_CAMERA_ROTATION,
                default=current_options.get(
                    CONF_CAMERA_ROTATION, DEFAULT_CAMERA_ROTATION
                ),
            ): vol.In(ROTATION_OPTIONS),
        })

        return self.async_show_form(
            step_id="init",
            data_schema=schema,
        )
