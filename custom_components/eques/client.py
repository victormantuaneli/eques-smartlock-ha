"""Eques Cloud WebSocket API Client."""

import asyncio
import hashlib
import json
import logging
import os
import re
import select
import socket
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
    CONF_CAMERA_RTSP_URL,
    DEFAULT_AUTO_RELOCK_SECONDS,
    DEFAULT_QUEUE_TIMEOUT,
    DEFAULT_CAMERA_ROTATION,
)

_LOGGER = logging.getLogger(__name__)


def compute_unlock_value(from_uid: str, to_uid: str) -> str:
    """Computes reverse-engineered cryptographic value for open_smart_lock payload.

    Algorithm decompiled from native libicvss.so / classes3.dex:
    token_str = from_uid + to_uid
    SHA-1(token_str) -> md5(sha1_bytes) -> hex string
    """
    token_str = f"{from_uid}{to_uid}"
    sha1_digest = hashlib.sha1(token_str.encode("utf-8")).digest()
    md5_hash = hashlib.md5(sha1_digest).hexdigest()
    return md5_hash


class EquesClient:
    """Async client managing persistent WebSocket connection with Eques cloud."""

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
        camera_rtsp_url: str = "",
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
        self.camera_rtsp_url = camera_rtsp_url or ""
        self.device_ip = None
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
                self._cache_file = os.path.join(
                    self.cache_dir, f"eques_snapshot_{self.device_uid}.jpg"
                )
                if os.path.exists(self._cache_file):
                    with open(self._cache_file, "rb") as f:
                        self.last_snapshot_bytes = f.read()
                        _LOGGER.info(
                            "Loaded cached doorbell snapshot from disk (%d bytes)",
                            len(self.last_snapshot_bytes),
                        )
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
        if CONF_CAMERA_RTSP_URL in options:
            self.camera_rtsp_url = options[CONF_CAMERA_RTSP_URL]
        _LOGGER.info(
            "Updated EquesClient options (user mappings: %s, rotation: %s, rtsp: %s)",
            self.user_mappings,
            self.camera_rotation,
            self.camera_rtsp_url,
        )
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
        if self.cloud_ws:
            await self.cloud_ws.close()
        if self._task:
            self._task.cancel()

    async def async_unlock(self) -> bool:
        """Triggers remote unlock command using the configured PIN."""
        if not self.pin:
            _LOGGER.error("Unlock requested but no PIN configured")
            return False

        if not self.session_bid or not self.device_uid:
            _LOGGER.error("Cannot unlock: missing session credentials")
            return False

        # Dispatch unlock with reinforce pulse
        asyncio.create_task(self._dispatch_unlock_burst(self.pin))
        return True

    def set_queue_enabled(self, enabled: bool):
        """Enables or disables auto-unlock on next doorbell ring."""
        self.queue_enabled = enabled
        if enabled:
            self.queue_expires_at = time.time() + self.queue_timeout
            _LOGGER.info(
                "Queue unlock on doorbell ring ENABLED (expires in %d seconds)",
                self.queue_timeout,
            )
        else:
            self.queue_expires_at = 0.0
            _LOGGER.info("Queue unlock on doorbell ring DISABLED")
        self._notify_callbacks()

    async def _send_unlock_payload(self, pin: str) -> bool:
        """Sends open_smart_lock payload over Cloud WebSocket."""
        if not self.cloud_ws or self.cloud_ws.closed:
            _LOGGER.error("Cannot send unlock: Cloud WebSocket is not connected")
            return False

        sec_val = compute_unlock_value(self.session_bid, self.device_uid)
        pin_md5 = hashlib.md5(pin.encode("utf-8")).hexdigest()

        payload = {
            "method": "open_smart_lock",
            "from": self.session_bid,
            "to": self.device_uid,
            "val": sec_val,
            "type": "open",
            "password": pin_md5,
        }

        try:
            _LOGGER.info(
                "Sending open_smart_lock payload to lock %s (user: %s)",
                self.device_uid,
                self.session_bid,
            )
            await self.cloud_ws.send_str(json.dumps(payload))
            self.is_locked = False
            self._notify_callbacks()
            asyncio.create_task(self._schedule_relock())
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
        _LOGGER.info(
            "Lock state auto-reset to locked (%ss timeout)", self.auto_relock_seconds
        )

    async def _schedule_doorbell_reset(self):
        """Resets the doorbell ring binary sensor after 15 seconds."""
        await asyncio.sleep(15)
        self.is_doorbell_ringing = False
        self._notify_callbacks()

    async def async_wake_camera(self) -> bool:
        """Wakes up the camera / requests video monitor stream via Cloud WebSocket."""
        if not self.cloud_ws or self.cloud_ws.closed or not self.session_bid:
            _LOGGER.warning("Cannot wake camera: cloud connection not active")
            return False

        payload = {
            "method": "call_v2",
            "from": self.session_bid,
            "to": self.device_uid,
            "channel_id": 0,
            "state": "invite",
            "netType": 1,
            "rtcserverip": "47.89.155.176",
            "rtcserverport": 8001,
            "rtcudpip": "47.89.155.176",
            "rtcudpport": 8001,
            "op_type": 1,
        }
        _LOGGER.info("Sending camera wake/invite command to lock %s", self.device_uid)
        try:
            await self.cloud_ws.send_str(json.dumps(payload))
            # Trigger background SSDP scan to discover local RTSP stream
            asyncio.create_task(self.async_discover_local_rtsp())
            return True
        except Exception as err:
            _LOGGER.error("Failed to send camera wake command: %s", err)
            return False

    async def async_discover_local_rtsp(self) -> str | None:
        """Discovers the lock's local RTSP stream URL via native SSDP probe."""
        if self.camera_rtsp_url:
            return self.camera_rtsp_url

        loop = asyncio.get_running_loop()
        rtsp_url = await loop.run_in_executor(None, self._ssdp_probe_sync)
        if rtsp_url:
            self.camera_rtsp_url = rtsp_url
            _LOGGER.info("Discovered local RTSP stream URL: %s", rtsp_url)
            self._notify_callbacks()
            return rtsp_url
        return None

    def _ssdp_probe_sync(self) -> str | None:
        """Synchronous UDP SSDP probe discovered from libicvss.so reverse engineering."""
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)
        sock.settimeout(2.5)

        try:
            # 16-byte native magic packet discovered in Search_Url / libicvss.so
            payload = b"1111111111111111"
            sock.sendto(payload, ("239.255.255.250", 1900))
            start = time.time()
            while time.time() - start < 3.0:
                r, _, _ = select.select([sock], [], [], 0.5)
                if r:
                    data, addr = sock.recvfrom(2048)
                    text = data.decode("utf-8", errors="ignore")
                    if "eques" in text.lower() or "8200" in text:
                        m = re.search(r"http://([0-9\.]+):", text)
                        if m:
                            ip = m.group(1)
                        else:
                            ip = addr[0]
                        self.device_ip = ip
                        return f"rtsp://{ip}:554/1"
        except Exception as err:
            _LOGGER.debug("SSDP probe exception: %s", err)
        finally:
            sock.close()
        return None

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
                            _LOGGER.info(
                                "Successfully fetched doorbell snapshot (%d bytes)",
                                len(data),
                            )
                            if self._cache_file:
                                try:
                                    with open(self._cache_file, "wb") as f:
                                        f.write(data)
                                except Exception as err:
                                    _LOGGER.warning(
                                        "Failed to save snapshot cache: %s", err
                                    )
                            self._notify_callbacks()
                            return data
                    else:
                        _LOGGER.warning(
                            "Snapshot download returned HTTP status %d", resp.status
                        )
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
                    async with session.ws_connect(
                        CLOUD_WS_URL, heartbeat=25, timeout=10
                    ) as ws:
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
                                        _LOGGER.info(
                                            "Authenticated as %s (UID: %s)",
                                            self.username,
                                            self.session_uid,
                                        )
                                        await ws.send_str(
                                            json.dumps({"method": "bdylist"})
                                        )
                                        await ws.send_str(
                                            json.dumps({"method": "getok"})
                                        )
                                        self._notify_callbacks()
                                    else:
                                        _LOGGER.error(
                                            "Authentication rejected: %s",
                                            payload.get("reason"),
                                        )

                                # 1b. Media Token (getok)
                                elif method == "getok":
                                    token = payload.get("token")
                                    if token:
                                        self.http_token = token
                                        _LOGGER.info(
                                            "Acquired Eques media token for doorbell snapshots"
                                        )

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
                                    self.last_ring_datetime = (
                                        datetime.fromtimestamp(now).strftime(
                                            "%Y-%m-%d %H:%M:%S"
                                        )
                                    )
                                    self._notify_callbacks()
                                    asyncio.create_task(self._schedule_doorbell_reset())
                                    # Trigger local stream discovery
                                    asyncio.create_task(
                                        self.async_discover_local_rtsp()
                                    )

                                    # Check queued unlock
                                    if (
                                        self.queue_enabled
                                        and now <= self.queue_expires_at
                                    ):
                                        _LOGGER.info(
                                            "Doorbell pressed with active queue! Auto-unlocking..."
                                        )
                                        asyncio.create_task(
                                            self._dispatch_unlock_burst(self.pin)
                                        )

                                # 4. Doorbell Ring (ring)
                                elif method == "ring":
                                    now = time.time()
                                    self.device_status = "awake"
                                    self.is_doorbell_ringing = True
                                    self.last_ring_time = int(now)
                                    self.last_ring_datetime = (
                                        datetime.fromtimestamp(now).strftime(
                                            "%Y-%m-%d %H:%M:%S"
                                        )
                                    )
                                    self._notify_callbacks()
                                    asyncio.create_task(self._schedule_doorbell_reset())
                                    asyncio.create_task(
                                        self.async_discover_local_rtsp()
                                    )

                                    if (
                                        self.queue_enabled
                                        and now <= self.queue_expires_at
                                    ):
                                        _LOGGER.info(
                                            "Doorbell ring with active queue! Auto-unlocking..."
                                        )
                                        asyncio.create_task(
                                            self._dispatch_unlock_burst(self.pin)
                                        )

                                # 4b. Doorbell Snapshot Upload (filetrans)
                                elif method == "filetrans":
                                    fid = payload.get("fid")
                                    filetime = payload.get("filetime")
                                    _LOGGER.info(
                                        "Received filetrans event (fid: %s, filetime: %s)",
                                        fid,
                                        filetime,
                                    )
                                    if fid:
                                        self.last_fid = fid
                                        self.last_snapshot_time = filetime
                                        asyncio.create_task(
                                            self.async_fetch_snapshot(fid)
                                        )

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
                                    elif (
                                        raw_nick
                                        and raw_nick != user_id
                                        and raw_nick != "I"
                                    ):
                                        friendly_nick = raw_nick
                                    else:
                                        friendly_nick = f"User {user_id}"

                                    self.last_unlock_type = unlock_type
                                    self.last_unlock_user = user_id
                                    self.last_unlock_nick = friendly_nick
                                    self.last_unlock_time = int(now)
                                    self.last_unlock_datetime = (
                                        datetime.fromtimestamp(now).strftime(
                                            "%Y-%m-%d %H:%M:%S"
                                        )
                                    )
                                    self.last_record_id = record_id
                                    self.is_locked = False
                                    self._notify_callbacks()
                                    asyncio.create_task(self._schedule_relock())

                            elif msg.type in (WSMsgType.CLOSED, WSMsgType.ERROR):
                                _LOGGER.warning("Cloud WebSocket closed or errored")
                                break

            except Exception as err:
                _LOGGER.error("WebSocket connection error: %s", err)

            self.connected_to_cloud = False
            self._notify_callbacks()
            if self._running:
                _LOGGER.info("Reconnecting to Eques Cloud in 5 seconds...")
                await asyncio.sleep(5)
