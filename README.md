# Eques Smart Lock & Doorbell - Home Assistant Integration

Custom integration to connect Eques Smart Locks and Video Doorbells to Home Assistant using direct cloud WebSocket push.

## Features

- **Lock Entity**: Remotely unlock using your PIN. Supports standby sleep wake-up (arms auto-unlock when doorbell rings).
- **Doorbell Camera**: Camera snapshot entity displaying the latest doorbell ring/alarm capture directly in Home Assistant dashboards.
- **Doorbell Sensor**: Real-time binary sensor triggering upon doorbell press or call invite.
- **Audit Sensors**:
  - Last Unlock Method (Keypad PIN, Fingerprint, RFID Card, Face Recognition, Remote App)
  - Last Unlock User (Mapped user nickname or ID)
  - Last Unlock Time
  - Last Doorbell Ring Time
  - Lock Device Status (awake / standby)
- **Queue Switch**: "Unlock on Doorbell Ring" switch to arm or disarm automatic unlocking on the next ring.
- **User ID Mapping**: Options flow to register human-readable names for user IDs 1 to 5 and custom IDs.
- **Localization**: Supports English (default) and Brazilian Portuguese.

## Installation

### Via HACS (Custom Repository)
1. In Home Assistant, open **HACS** > **Integrations**.
2. Click the three dots in the top right corner and choose **Custom repositories**.
3. Add the repository URL, select category **Integration**, and click **Add**.
4. Search for **Eques Smart Lock & Doorbell**, click **Download**, and restart Home Assistant.

### Manual Installation
1. Copy the `custom_components/eques` directory into your Home Assistant `<config>/custom_components/` folder.
2. Restart Home Assistant.

## Configuration

1. In Home Assistant, navigate to **Settings** > **Devices & Services** > **Add Integration**.
2. Search for **Eques Smart Lock & Doorbell**.
3. Enter your Eques cloud credentials:
   - **Username / Email / Phone**
   - **Password**
   - **Remote Unlock PIN**
4. Submit to discover and configure your device.

## User Mapping (Options Flow)

To configure friendly names for your lock users:
1. Go to **Settings** > **Devices & Services** > **Eques**.
2. Click **Configure**.
3. Set names for User IDs 1-5 or enter additional mappings in the multiline field (`ID: Name`).
4. Save to apply changes immediately without restarting.
