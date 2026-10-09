# RespiratoryCare IoT Simulator

Firmware simulator for local development and end-to-end testing of the RespiCare AIoT system.

## Flow

```text
Stethoscope Simulator
→ MQTT events/status
→ Web Backend
→ Supabase Storage
→ Recording Complete
→ AI Analysis
→ Web UI
```

The simulator does not call the AI server directly.

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
```

Required `.env` values:

```env
WEB_BASE_URL=http://localhost:3000
DEVICE_API_KEY=

STETHOSCOPE_DEVICE_ID=RESPICARE-STETH-001

MQTT_HOST=localhost
MQTT_PORT=1883
```

`DEVICE_API_KEY` must match `FIRMWARE_DEVICE_API_KEY` in the web backend.

## MQTT

Start Mosquitto:

```bash
docker compose -f mqtt/docker-compose.yml up -d
```

Stop:

```bash
docker compose -f mqtt/docker-compose.yml down
```

## Run Stethoscope Simulator

WAV requirement: PCM, mono, 16-bit, 16 kHz.

```bash
python -m simulators.stethoscope.simulator \
  --visit-id <VISIT_UUID> \
  --wav /path/to/test-16k-mono.wav
```

The simulator performs:

```text
RECORDING_STARTED
→ RECORDING_STOPPED
→ POST upload-url
→ PUT WAV
→ POST /complete
```

## SpO₂ Simulator

```bash
python -m simulators.spo2.simulator \
  --visit-id <VISIT_UUID> \
  --spo2 97
```

## Tests

```bash
pytest tests/ -v
```

## MQTT Topics

```text
respicare/device/{deviceId}/command
respicare/device/{deviceId}/event
respicare/device/{deviceId}/status
```

WAV files are uploaded via HTTPS, not MQTT.

See `docs/MQTT_PROTOCOL.md` for protocol details.
