"""Constants for the Eques Smart Lock & Doorbell integration."""

DOMAIN = "eques"

# Configuration keys
CONF_USERNAME = "username"
CONF_PASSWORD = "password"
CONF_PIN = "pin"
CONF_DEVICE_UID = "device_uid"
CONF_DEVICE_NAME = "device_name"
CONF_AUTO_RELOCK_SECONDS = "auto_relock_seconds"
CONF_QUEUE_TIMEOUT = "queue_timeout"
CONF_USER_MAPPINGS = "user_mappings"
CONF_CAMERA_ROTATION = "camera_rotation"
CONF_CAMERA_RTSP_URL = "camera_rtsp_url"

# Default configuration values
DEFAULT_AUTO_RELOCK_SECONDS = 10
DEFAULT_QUEUE_TIMEOUT = 300
DEFAULT_CAMERA_ROTATION = 90
ROTATION_OPTIONS = [0, 90, 180, 270]

# Cloud WebSocket Configuration
CLOUD_HOST = "us-virginia-j1.ecamzone.cc"
CLOUD_WS_URL = f"ws://{CLOUD_HOST}:80/eques/icvss/login?sub=user&v=10"
APP_KEY = "8QYyilLNP1VtBQhMdXgKEAbRB6nKBDuV"
APP_ID = 1015

# Supported platforms
PLATFORMS = ["lock", "binary_sensor", "sensor", "switch", "camera", "button"]
