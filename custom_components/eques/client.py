"""Eques Cloud WebSocket API Client."""

import asyncio
import hashlib
import json
import logging
import os
import time
from datetime import datetime
from aiohttp import ClientSession, WSMsgType

from .const import (
    APP_ID,
    APP_KEY,
    CLOUD_HOST,
    CLOUD_WS_URL,
    CONF_AUTO_RELOCK_SECONDS,
    CONF_QUEUE_TIMEOUT,
    CONF_USER_MAPPINGS,
    CONF_CAMERA_ROTATION,
    DEFAULT_AUTO_RELOCK_SECONDS,
    DEFAULT_QUEUE_TIMEOUT,
    DEFAULT_CAMERA_ROTATION,
)

_LOGGER = logging.getLogger(__name__)


def compute_unlock_value(from_uid: str, to_uid: str) -> str:
    """Computes reverse-engineered cryptographic value for open_smart_lock payload."""
    part_from = from_uid[0:4] + from_uid[5:11] + from_uid[23:29]
    part_to = to_uid[3:7] + to_uid[23:27]
    raw = part_from + part_to + "EquesPWY"
    return hashlib.md5(raw.encode("utf-8")).hexdigest()


class EquesClient:
    """Manages persistent authenticated WebSocket connection to Eques Cloud."""

    def __init__(
        self,
        username: str,
        password: str,
        pin: str,
        device_uid: str,
        auto_relock_seconds: int = DEFAULT_AUTO_RELOCK_SECONDS,
        queue_timeout: int = DEFAULT_QUEUE_TIMEOUT,
        user_mappings: dict = None,
        camera_rotation: int = DEFAULT_CAMERA_ROTATION,
        cache_dir: str = None,
    ):
        self.username = username
        self.password = password
        self.pin = pin
        self.device_uid = device_uid
        self.auto_relock_seconds = auto_relock_seconds
        self.queue_timeout = queue_timeout
        self.user_mappings = user_mappings or {}
        self.camera_rotation = camera_rotation
        self.cache_dir = cache_dir

        self.session_bid = None
        self.session_uid = None
        self.http_token = None
        self.last_fid = None
        self.last_snapshot_bytes = None
        self.last_snapshot_time = None
        self._cache_file = None

        if self.cache_dir:
            try:
                os.makedirs(self.cache_dir, exist_ok=True)
                self._cache_file = os.path.join(self.cache_dir, f"eques_snapshot_{self.device_uid}.jpg")
                if os.path.exists(self._cache_file):
                    with open(self._cache_file, "rb") as f:
                        self.last_snapshot_bytes = f.read()
                        _LOGGER.info("Loaded cached doorbell snapshot from disk (%d bytes)", len(self.last_snapshot_bytes))
            except Exception as err:
                _LOGGER.warning("Could not initialize snapshot disk cache: %s", err)

        self.cloud_ws = None
        self._running = False
        self._task = None
        self._callbacks = set()

        # State attributes
        self.is_locked = True
        self.device_status = "standby"
        self.connected_to_cloud = False
        self.is_doorbell_ringing = False
        self.last_ring_time = None
        self.last_ring_datetime = None
        self.last_unlock_type = None
        self.last_unlock_user = None
        self.last_unlock_nick = None
        self.last_unlock_time = None
        self.last_unlock_datetime = None
        self.last_record_id = None

        # Queue on ring state
        self.queue_enabled = False
        self.queue_expires_at = 0.0

    def update_options(self, options: dict):
        """Updates client options dynamically from Home Assistant options flow."""
        if CONF_USER_MAPPINGS in options:
            self.user_mappings = options[CONF_USER_MAPPINGS]
        if CONF_AUTO_RELOCK_SECONDS in options:
            self.auto_relock_seconds = options[CONF_AUTO_RELOCK_SECONDS]
        if CONF_QUEUE_TIMEOUT in options:
            self.queue_timeout = options[CONF_QUEUE_TIMEOUT]
        if CONF_CAMERA_ROTATION in options:
            self.camera_rotation = options[CONF_CAMERA_ROTATION]
        _LOGGER.info("Updated EquesClient options (user mappings: %s, rotation: %s)", self.user_mappings, self.camera_rotation)
        self._notify_callbacks()

    def register_callback(self, callback):
        """Register a callback for state changes."""
        self._callbacks.add(callback)

    def remove_callback(self, callback):
        """Remove a previously registered callback."""
        self._callbacks.discard(callback)

    def _notify_callbacks(self):
        """Invoke all registered entity update callbacks."""
        for callback in list(self._callbacks):
            try:
                callback()
            except Exception as err:
                _LOGGER.error("Error executing callback: %s", err)

    async def start(self):
        """Starts the background WebSocket client loop."""
        self._running = True
        self._task = asyncio.create_task(self._websocket_loop())

    async def stop(self):
        """Stops the client and closes WebSocket connection."""
        self._running = False
        if self.cloud_ws and not self.cloud_ws.closed:
            await self.cloud_ws.close()
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    def arm_unlock_queue(self, timeout: int = None):
        """Arms the unlock queue so the door automatically unlocks on next ring."""
        now = time.time()
        timeout_to_use = timeout or self.queue_timeout
        self.queue_enabled = True
        self.queue_expires_at = now + timeout_to_use
        _LOGGER.info("Unlock queue armed for %s seconds", timeout_to_use)
        self._notify_callbacks()

    def disarm_unlock_queue(self):
        """Disarms the unlock queue."""
        self.queue_enabled = False
        self.queue_expires_at = 0.0
        _LOGGER.info("Unlock queue disarmed")
        self._notify_callbacks()

    async def async_unlock(self, pin: str = None, arm_if_sleeping: bool = True):
        """
        Sends remote unlock command.
        If device is sleeping, arms queue to unlock on doorbell interaction.
        """
        pin_to_use = pin or self.pin
        if arm_if_sleeping:
            self.arm_unlock_queue(self.queue_timeout)

        # Dispatch immediate packet
        await self._send_unlock_payload(pin_to_use)

    async def _send_unlock_payload(self, pin: str):
        """Builds and sends open_smart_lock payload over WebSocket."""
        if not self.cloud_ws or self.cloud_ws.closed or not self.session_uid:
            _LOGGER.warning("Cannot send unlock: WebSocket is not connected or authenticated")
            return False

        now_ts = int(time.time())
        hash_value = compute_unlock_value(self.session_uid, self.device_uid)

        unlock_cmd = {
            "method": "open_smart_lock",
            "from": self.session_uid,
            "to": self.device_uid,
            "value": hash_value,
            "userBid": self.session_bid if self.session_bid else self.session_uid,
            "time": now_ts,
            "pwd": str(pin),
        }

        try:
            await self.cloud_ws.send_str(json.dumps(unlock_cmd))
            _LOGGER.info("Dispatched open_smart_lock to %s", self.device_uid)
            return True
        except Exception as err:
            _LOGGER.error("Failed to send open_smart_lock: %s", err)
            return False

    async def _dispatch_unlock_burst(self, pin: str):
        """Sends unlock command with an 800ms reinforcement pulse."""
        await self._send_unlock_payload(pin)
        await asyncio.sleep(0.8)
        if self.is_locked:
            _LOGGER.info("Sending reinforcement unlock pulse during open call channel")
            await self._send_unlock_payload(pin)

    async def _schedule_relock(self):
        """Schedules auto-relock state reset."""
        await asyncio.sleep(self.auto_relock_seconds)
        self.is_locked = True
        self._notify_callbacks()
        _LOGGER.info("Lock state auto-reset to locked (%ss timeout)", self.auto_relock_seconds)

    async def _schedule_doorbell_reset(self):
        """Resets the doorbell ring binary sensor after 15 seconds."""
        await asyncio.sleep(15)
        self.is_doorbell_ringing = False
        self._notify_callbacks()

    async def async_fetch_snapshot(self, fid: str = None) -> bytes | None:
        """Downloads the snapshot for the given fid (or last_fid) from Eques Cloud."""
        target_fid = fid or self.last_fid
        if not target_fid:
            _LOGGER.debug("No FID available to fetch snapshot")
            return None
        if not self.session_bid or not self.http_token:
            _LOGGER.warning("Cannot download snapshot: session_bid or http_token not ready")
            return None

        url = (
            f"http://{CLOUD_HOST}/eques/icvss/file-down"
            f"?uid={self.session_bid}&token={self.http_token}&fid={target_fid}&devid={self.device_uid}"
        )
        _LOGGER.info("Fetching doorbell snapshot from %s", url)

        try:
            async with ClientSession() as session:
                async with session.get(url, timeout=15) as resp:
                    if resp.status == 200:
                        data = await resp.read()
                        if len(data) > 100:
                            self.last_snapshot_bytes = data
                            self.last_fid = target_fid
                            _LOGGER.info("Successfully fetched doorbell snapshot (%d bytes)", len(data))
                            if self._cache_file:
                                try:
                                    with open(self._cache_file, "wb") as f:
                                        f.write(data)
                                except Exception as err:
                                    _LOGGER.warning("Failed to save snapshot cache: %s", err)
                            self._notify_callbacks()
                            return data
                    else:
                        _LOGGER.warning("Snapshot download returned HTTP status %d", resp.status)
        except Exception as err:
            _LOGGER.error("Error downloading snapshot fid %s: %s", target_fid, err)
        return None

    async def _websocket_loop(self):
        """Maintains persistent connection and dispatches received messages."""
        password_md5 = hashlib.md5(self.password.encode("utf-8")).hexdigest()
        login_payload = {
            "method": "login_v2",
            "name_stype": "uname",
            "name": self.username,
            "token_stype": "passwd_md5",
            "token": password_md5,
            "app_key": APP_KEY,
            "app_id": APP_ID,
        }

        while self._running:
            try:
                _LOGGER.info("Connecting to Eques Cloud (%s)...", CLOUD_HOST)
                async with ClientSession() as session:
                    async with session.ws_connect(CLOUD_WS_URL, heartbeat=25, timeout=10) as ws:
                        self.cloud_ws = ws
                        await ws.send_str(json.dumps(login_payload))

                        async for msg in ws:
                            if not self._running:
                                break
                            if msg.type == WSMsgType.TEXT:
                                try:
                                    payload = json.loads(msg.data)
                                except Exception:
                                    continue

                                method = payload.get("method")
                                code = payload.get("code")

                                # 1. Login Ack
                                if method == "login_v2":
                                    if code == 4000:
                                        self.session_bid = payload.get("bid")
                                        self.session_uid = payload.get("uid")
                                        self.connected_to_cloud = True
                                        _LOGGER.info("Authenticated as %s (UID: %s)", self.username, self.session_uid)
                                        await ws.send_str(json.dumps({"method": "bdylist"}))
                                        await ws.send_str(json.dumps({"method": "getok"}))
                                        self._notify_callbacks()
                                    else:
                                        _LOGGER.error("Authentication rejected: %s", payload.get("reason"))

                                # 1b. Media Token (getok)
                                elif method == "getok":
                                    token = payload.get("token")
                                    if token:
                                        self.http_token = token
                                        _LOGGER.info("Acquired Eques media token for doorbell snapshots")

                                # 2. Device Status (devst)
                                elif method == "devst":
                                    dev_status = payload.get("status")
                                    dev_stat = payload.get("stat")
                                    if dev_status == 1 or dev_stat in (1, 2):
                                        self.device_status = "awake"
                                    elif dev_status == 0 and dev_stat == 0:
                                        self.device_status = "standby"
                                    self._notify_callbacks()

                                # 3. Doorbell Call (call_v2)
                                elif method == "call_v2":
                                    now = time.time()
                                    self.device_status = "awake"
                                    self.is_doorbell_ringing = True
                                    self.last_ring_time = int(now)
                                    self.last_ring_datetime = datetime.fromtimestamp(now).strftime("%Y-%m-%d %H:%M:%S")
                                    self._notify_callbacks()
                                    asyncio.create_task(self._schedule_doorbell_reset())

                                    # Check queued unlock
                                    if self.queue_enabled and now <= self.queue_expires_at:
                                        _LOGGER.info("Doorbell pressed with active queue! Auto-unlocking...")
                                        asyncio.create_task(self._dispatch_unlock_burst(self.pin))

                                # 4. Doorbell Ring (ring)
                                elif method == "ring":
                                    now = time.time()
                                    self.device_status = "awake"
                                    self.is_doorbell_ringing = True
                                    self.last_ring_time = int(now)
                                    self.last_ring_datetime = datetime.fromtimestamp(now).strftime("%Y-%m-%d %H:%M:%S")
                                    self._notify_callbacks()
                                    asyncio.create_task(self._schedule_doorbell_reset())

                                    if self.queue_enabled and now <= self.queue_expires_at:
                                        _LOGGER.info("Doorbell ring with active queue! Auto-unlocking...")
                                        asyncio.create_task(self._dispatch_unlock_burst(self.pin))

                                # 4b. Doorbell Snapshot Upload (filetrans)
                                elif method == "filetrans":
                                    fid = payload.get("fid")
                                    filetime = payload.get("filetime")
                                    _LOGGER.info("Received filetrans event (fid: %s, filetime: %s)", fid, filetime)
                                    if fid:
                                        self.last_fid = fid
                                        self.last_snapshot_time = filetime
                                        asyncio.create_task(self.async_fetch_snapshot(fid))

                                # 5. Lock Activity Messages
                                elif method == "smart_lock_msg":
                                    unlock_type = payload.get("type")
                                    user_id = str(payload.get("identifier", ""))
                                    raw_nick = payload.get("iden_nick", "")
                                    record_id = payload.get("record_id", "")
                                    now = time.time()

                                    # Check custom user mapping from Options Flow
                                    mapped_name = self.user_mappings.get(user_id)
                                    if mapped_name:
                                        friendly_nick = mapped_name
                                    elif raw_nick and raw_nick != user_id and raw_nick != "I":
                                        friendly_nick = raw_nick
                                    elif unlock_type == 7:
                                        friendly_nick = self.username
                                    elif user_id:
                                        friendly_nick = f"User {user_id}"
                                    else:
                                        friendly_nick = "Unknown"

                                    type_map = {
                                        1: "Keypad PIN",
                                        2: "Fingerprint",
                                        3: "RFID Card",
                                        7: "Remote App",
                                        10: "Face Recognition / Keypad",
                                        15: "Smart Lock State",
                                    }
                                    type_str = type_map.get(unlock_type, f"Type {unlock_type}")
                                    self.device_status = "awake"

                                    # type 1..10 (or any message with user identifier except 15) represents an unlock
                                    if unlock_type in (1, 2, 3, 4, 5, 6, 7, 10) or (user_id and unlock_type != 15):
                                        self.last_unlock_type = type_str
                                        self.last_unlock_user = user_id
                                        self.last_unlock_nick = friendly_nick
                                        self.last_unlock_time = int(now)
                                        self.last_unlock_datetime = datetime.fromtimestamp(now).strftime("%Y-%m-%d %H:%M:%S")
                                        self.last_record_id = record_id

                                        self.queue_enabled = False
                                        self.is_locked = False
                                        _LOGGER.info("Lock unlocked via %s by %s (%s)", type_str, friendly_nick, user_id)
                                        self._notify_callbacks()
                                        asyncio.create_task(self._schedule_relock())

                                # 6. Remote Unlock Confirmations
                                elif method in ("open_smart_lock_result", "open_smart_lock_response"):
                                    ret = payload.get("status", payload.get("ret", payload.get("code", 0)))
                                    now = time.time()
                                    if ret == 0 or ret == 4000:
                                        self.queue_enabled = False
                                        self.is_locked = False
                                        self.last_unlock_type = "Remote App"
                                        self.last_unlock_time = int(now)
                                        self.last_unlock_datetime = datetime.fromtimestamp(now).strftime("%Y-%m-%d %H:%M:%S")
                                        if not self.last_unlock_nick:
                                            self.last_unlock_nick = self.user_mappings.get("app") or self.username
                                        _LOGGER.info("Remote unlock confirmed by physical lock")
                                        self._notify_callbacks()
                                        asyncio.create_task(self._schedule_relock())

                            elif msg.type in (WSMsgType.CLOSED, WSMsgType.ERROR):
                                _LOGGER.warning("WebSocket disconnected: %s", msg)
                                break

            except Exception as err:
                _LOGGER.error("WebSocket connection error: %s", err)
            finally:
                self.cloud_ws = None
                self.connected_to_cloud = False
                self._notify_callbacks()
                if self._running:
                    await asyncio.sleep(5)
