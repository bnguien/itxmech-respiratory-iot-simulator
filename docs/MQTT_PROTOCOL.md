# RespiCare MQTT Protocol Reference

> **Version**: 1  
> **Last updated**: October 2026  
> **Repository**: `itxmech-respiratory-iot-simulator`

---

## Overview

This document defines the complete MQTT communication protocol used between RespiCare IoT devices and the web backend. All messages use **JSON (UTF-8)** payloads.

**Critical rule**: WAV audio files are **never** transferred over MQTT. All audio goes via HTTPS directly to Supabase Storage using a signed URL obtained from the web backend.

---

## Device IDs

| Device                    | Device ID                |
|---------------------------|--------------------------|
| Electronic stethoscope    | `RESPICARE-STETH-001`    |
| SpO2 wearable             | `RESPICARE-SPO2-001`     |

Device IDs are configured via the `STETHOSCOPE_DEVICE_ID` and `SPO2_DEVICE_ID` environment variables.

---

## Topic Structure

```
respicare/device/{deviceId}/command   # Web → Device
respicare/device/{deviceId}/event     # Device → Web
respicare/device/{deviceId}/status    # Device presence (retained)
```

### Examples

```
respicare/device/RESPICARE-STETH-001/command
respicare/device/RESPICARE-STETH-001/event
respicare/device/RESPICARE-STETH-001/status

respicare/device/RESPICARE-SPO2-001/event
respicare/device/RESPICARE-SPO2-001/status
```

---

## QoS Recommendations

| Topic / Message Type      | QoS | Retained | Rationale                          |
|---------------------------|-----|----------|------------------------------------|
| Commands                  | 1   | No       | Must be delivered at least once    |
| Device events             | 1   | No       | Must be delivered at least once    |
| Device status (online)    | 1   | **Yes**  | New subscribers see current state  |
| Device status (offline)   | 1   | **Yes**  | Persisted until device reconnects  |
| SpO2 real-time readings   | 0   | No       | Low latency preferred; tolerate loss |

---

## Common Message Fields

Every message includes these base fields:

```json
{
  "version": 1,
  "type": "MESSAGE_TYPE",
  "messageId": "550e8400-e29b-41d4-a716-446655440000",
  "deviceId": "RESPICARE-STETH-001",
  "visitId": "f47ac10b-58cc-4372-a567-0e02b2c3d479",
  "timestamp": "2026-10-08T15:30:00.000Z"
}
```

| Field       | Type   | Required | Description                                |
|-------------|--------|----------|--------------------------------------------|
| `version`   | int    | Yes      | Protocol version (currently `1`)           |
| `type`      | string | Yes      | Message type identifier                    |
| `messageId` | string | Yes      | UUID v4 — for idempotency / deduplication |
| `deviceId`  | string | Context  | Omitted in commands sent to a specific topic |
| `visitId`   | string | Context  | Present when message relates to a visit    |
| `timestamp` | string | Yes      | ISO-8601 UTC (e.g. `2026-10-08T15:30:00.000Z`) |

### `messageId`

Each message carries a unique UUID v4 `messageId`. This enables future duplicate-detection and idempotent processing. Consumers should log the `messageId` and may choose to discard messages with a previously-seen ID.

### `timestamp`

Always UTC, ISO-8601 format with millisecond precision and `Z` suffix.

### `visitId` Relationship

The `visitId` ties all messages for one clinical visit together:
- Assigned by the web backend in the `ASSIGN_VISIT` command
- Included in all subsequent stethoscope events for that visit
- Used as the key to look up/create the recording on the backend
- Included in SpO2 readings when a visit is active

---

## Commands (Web → Device)

Commands are published by the web backend on `respicare/device/{deviceId}/command`.

### `ASSIGN_VISIT`

Assigns a patient visit to the stethoscope. The device stores this in memory and uses the `visitId` for subsequent events and the upload flow.

**Topic**: `respicare/device/RESPICARE-STETH-001/command`

```json
{
  "version": 1,
  "type": "ASSIGN_VISIT",
  "messageId": "550e8400-e29b-41d4-a716-446655440000",
  "visitId": "f47ac10b-58cc-4372-a567-0e02b2c3d479",
  "timestamp": "2026-10-08T15:30:00.000Z"
}
```

---

## Stethoscope Events (Device → Web)

Events are published by the device on `respicare/device/{deviceId}/event` with **QoS 1**.

### `VISIT_ASSIGNED`

Published by the device to confirm it has received and stored the visit assignment.

```json
{
  "version": 1,
  "type": "VISIT_ASSIGNED",
  "messageId": "...",
  "deviceId": "RESPICARE-STETH-001",
  "visitId": "f47ac10b-58cc-4372-a567-0e02b2c3d479",
  "timestamp": "2026-10-08T15:30:01.000Z"
}
```

### `RECORDING_STARTED`

Published immediately when the device begins capturing audio.

```json
{
  "version": 1,
  "type": "RECORDING_STARTED",
  "messageId": "...",
  "deviceId": "RESPICARE-STETH-001",
  "visitId": "f47ac10b-58cc-4372-a567-0e02b2c3d479",
  "timestamp": "2026-10-08T15:30:02.000Z"
}
```

### `RECORDING_STOPPED`

Published when audio capture is complete.

```json
{
  "version": 1,
  "type": "RECORDING_STOPPED",
  "messageId": "...",
  "deviceId": "RESPICARE-STETH-001",
  "visitId": "f47ac10b-58cc-4372-a567-0e02b2c3d479",
  "timestamp": "2026-10-08T15:30:12.000Z"
}
```

### `UPLOAD_STARTED`

Published just before the WAV file upload begins. Includes the `recordingId` from the backend.

```json
{
  "version": 1,
  "type": "UPLOAD_STARTED",
  "messageId": "...",
  "deviceId": "RESPICARE-STETH-001",
  "visitId": "f47ac10b-58cc-4372-a567-0e02b2c3d479",
  "recordingId": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "timestamp": "2026-10-08T15:30:13.000Z"
}
```

### `UPLOAD_SUCCESS`

Published after `POST /api/device/recordings/{recordingId}/complete` returns success.

```json
{
  "version": 1,
  "type": "UPLOAD_SUCCESS",
  "messageId": "...",
  "deviceId": "RESPICARE-STETH-001",
  "visitId": "f47ac10b-58cc-4372-a567-0e02b2c3d479",
  "recordingId": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "timestamp": "2026-10-08T15:30:17.000Z"
}
```

### `UPLOAD_FAILED`

Published when any step of the upload flow fails. Contains a safe error description (no secrets).

```json
{
  "version": 1,
  "type": "UPLOAD_FAILED",
  "messageId": "...",
  "deviceId": "RESPICARE-STETH-001",
  "visitId": "f47ac10b-58cc-4372-a567-0e02b2c3d479",
  "recordingId": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "error": "WAV upload failed: HTTP 403 – signed URL expired.",
  "timestamp": "2026-10-08T15:30:15.000Z"
}
```

---

## Device Status (Retained)

Status messages are published on `respicare/device/{deviceId}/status` as **retained** messages with QoS 1.

Because they are retained, any new subscriber (the web backend) immediately receives the device's current state without waiting for the device to publish again.

### `DEVICE_ONLINE`

Published by the device when it successfully connects to the MQTT broker.

```json
{
  "version": 1,
  "type": "DEVICE_ONLINE",
  "messageId": "...",
  "deviceId": "RESPICARE-STETH-001",
  "timestamp": "2026-10-08T15:29:58.000Z"
}
```

### `DEVICE_OFFLINE`

Published by the device on clean shutdown. Also published automatically by the MQTT broker via **Last Will** if the device disconnects unexpectedly.

```json
{
  "version": 1,
  "type": "DEVICE_OFFLINE",
  "messageId": "...",
  "deviceId": "RESPICARE-STETH-001",
  "timestamp": "2026-10-08T15:29:57.000Z"
}
```

### Last Will Behaviour

When the stethoscope simulator connects to the broker, it registers a **Last Will and Testament (LWT)**:

- **Topic**: `respicare/device/RESPICARE-STETH-001/status`
- **Payload**: `DEVICE_OFFLINE` JSON message
- **QoS**: 1
- **Retain**: `true`

If the simulator process dies unexpectedly (crash, power loss, network cut), the broker automatically publishes the LWT to the status topic so the web backend knows the device went offline.

---

## SpO2 Events (Device → Web)

### `SPO2_READING`

Published at a regular interval (e.g., every 5 seconds) using **QoS 0** (best-effort) to prioritise low latency over guaranteed delivery.

**Topic**: `respicare/device/RESPICARE-SPO2-001/event`

```json
{
  "version": 1,
  "type": "SPO2_READING",
  "messageId": "...",
  "deviceId": "RESPICARE-SPO2-001",
  "visitId": "f47ac10b-58cc-4372-a567-0e02b2c3d479",
  "spo2": 97,
  "timestamp": "2026-10-08T15:30:05.000Z"
}
```

| Field     | Type | Range  | Description              |
|-----------|------|--------|--------------------------|
| `spo2`    | int  | 0–100  | SpO2 percentage          |

---

## HTTPS WAV Upload Flow

> **WAV files must NEVER be transferred over MQTT.**

The complete upload flow uses HTTPS:

```
Device                    Web Backend               Supabase Storage
  │                            │                           │
  │  POST /upload-url          │                           │
  │ ─────────────────────────► │                           │
  │                            │  Create recording         │
  │                            │  Generate signed URL      │
  │  { recordingId, uploadUrl }│                           │
  │ ◄───────────────────────── │                           │
  │                            │                           │
  │  PUT WAV (binary)          │                           │
  │ ──────────────────────────────────────────────────────►│
  │                            │                           │
  │  POST /complete            │                           │
  │ ─────────────────────────► │                           │
  │                            │  Trigger AI analysis      │
  │  200 OK                    │                           │
  │ ◄───────────────────────── │                           │
```

### Step 1: Request signed URL

```
POST /api/device/visits/{visitId}/recording/upload-url
X-Device-Key: <DEVICE_API_KEY>
```

Response:

```json
{
  "recordingId": "...",
  "uploadUrl": "https://storage.supabase.co/..."
}
```

### Step 2: Upload WAV to Supabase Storage

```
PUT <uploadUrl>
Content-Type: audio/wav
Body: <WAV binary>
```

### Step 3: Mark recording complete

```
POST /api/device/recordings/{recordingId}/complete
X-Device-Key: <DEVICE_API_KEY>
```

The web backend then automatically triggers AI analysis. The device simulator's responsibility ends here.

---

## Required WAV Format

| Property    | Value              |
|-------------|--------------------|
| Container   | WAV                |
| Encoding    | PCM (linear, uncompressed) |
| Channels    | 1 (mono)           |
| Bit depth   | 16-bit             |
| Sample rate | 16,000 Hz          |

The simulator validates WAV metadata before uploading and rejects non-compliant files with a clear error.

---

## Security Notes

- Device API key is sent as `X-Device-Key` header over HTTPS only.
- MQTT credentials (`MQTT_USERNAME`, `MQTT_PASSWORD`) are optional for local development but should be set in staging/production.
- TLS should be enabled for the MQTT broker in non-local environments (port 8883).
- Signed upload URLs should be treated as secrets and never logged in full.
