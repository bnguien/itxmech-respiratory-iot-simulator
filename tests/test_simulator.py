"""
Unit tests for the RespiCare IoT Simulator.

All tests are self-contained and do not require:
- A running MQTT broker
- The real web backend
- A real WAV file (tests generate minimal valid WAV bytes in memory)
- The AI server

Run with:
    pytest tests/ -v
"""

from __future__ import annotations

import io
import json
import struct
import uuid
import wave
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_wav_bytes(
    channels: int = 1,
    sample_rate: int = 16000,
    sample_width: int = 2,
    n_frames: int = 1600,  # 0.1 seconds of silence
) -> bytes:
    """Generate minimal valid WAV bytes in memory."""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(channels)
        wf.setframerate(sample_rate)
        wf.setsampwidth(sample_width)
        wf.writeframes(b"\x00" * n_frames * channels * sample_width)
    return buf.getvalue()


def write_wav(tmp_path: Path, **kwargs: Any) -> Path:
    """Write a WAV file to tmp_path and return its Path."""
    p = tmp_path / "test.wav"
    p.write_bytes(make_wav_bytes(**kwargs))
    return p


# ===========================================================================
# 1. MQTT payload serialisation
# ===========================================================================


class TestMqttPayloadSerialisation:
    def test_base_message_json_has_camel_case_keys(self) -> None:
        from common.models import RecordingStartedEvent

        event = RecordingStartedEvent(
            device_id="RESPICARE-STETH-001",
            visit_id="visit-123",
        )
        data = json.loads(event.to_json())
        assert "messageId" in data, "messageId should be camelCase on the wire"
        assert "deviceId" in data
        assert "visitId" in data
        assert "timestamp" in data
        assert data["version"] == 1
        assert data["type"] == "RECORDING_STARTED"

    def test_message_excludes_none_fields(self) -> None:
        from common.models import RecordingStartedEvent

        event = RecordingStartedEvent(device_id="RESPICARE-STETH-001")
        data = json.loads(event.to_json())
        # visitId not set → should be absent
        assert "visitId" not in data

    def test_upload_started_includes_recording_id(self) -> None:
        from common.models import UploadStartedEvent

        event = UploadStartedEvent(
            device_id="RESPICARE-STETH-001",
            visit_id="visit-abc",
            recording_id="rec-xyz",
        )
        data = json.loads(event.to_json())
        assert data["recordingId"] == "rec-xyz"

    def test_upload_failed_includes_error(self) -> None:
        from common.models import UploadFailedEvent

        event = UploadFailedEvent(
            device_id="RESPICARE-STETH-001",
            visit_id="visit-abc",
            error="Signed URL expired.",
        )
        data = json.loads(event.to_json())
        assert data["error"] == "Signed URL expired."

    def test_spo2_reading_event(self) -> None:
        from common.models import Spo2ReadingEvent

        event = Spo2ReadingEvent(
            device_id="RESPICARE-SPO2-001",
            visit_id="visit-xyz",
            spo2=98,
        )
        data = json.loads(event.to_json())
        assert data["type"] == "SPO2_READING"
        assert data["spo2"] == 98

    def test_spo2_invalid_range_raises(self) -> None:
        from pydantic import ValidationError

        from common.models import Spo2ReadingEvent

        with pytest.raises(ValidationError):
            Spo2ReadingEvent(device_id="x", spo2=101)

        with pytest.raises(ValidationError):
            Spo2ReadingEvent(device_id="x", spo2=-1)

    def test_device_status_online(self) -> None:
        from common.models import DeviceStatusMessage

        msg = DeviceStatusMessage(
            type="DEVICE_ONLINE",
            device_id="RESPICARE-STETH-001",
        )
        data = json.loads(msg.to_json())
        assert data["type"] == "DEVICE_ONLINE"

    def test_device_status_offline(self) -> None:
        from common.models import DeviceStatusMessage

        msg = DeviceStatusMessage(
            type="DEVICE_OFFLINE",
            device_id="RESPICARE-STETH-001",
        )
        data = json.loads(msg.to_json())
        assert data["type"] == "DEVICE_OFFLINE"

    def test_assign_visit_command(self) -> None:
        from common.models import AssignVisitCommand

        cmd = AssignVisitCommand(visit_id="visit-001")
        data = json.loads(cmd.to_json())
        assert data["type"] == "ASSIGN_VISIT"
        assert data["visitId"] == "visit-001"


# ===========================================================================
# 2. messageId generation
# ===========================================================================


class TestMessageIdGeneration:
    def test_message_id_is_uuid4(self) -> None:
        from common.models import new_message_id

        msg_id = new_message_id()
        parsed = uuid.UUID(msg_id, version=4)
        assert str(parsed) == msg_id

    def test_each_message_gets_unique_id(self) -> None:
        from common.models import RecordingStartedEvent

        ids = {RecordingStartedEvent(device_id="x").message_id for _ in range(50)}
        assert len(ids) == 50, "All 50 messageIds should be unique"

    def test_utc_now_format(self) -> None:
        from common.models import utc_now

        ts = utc_now()
        assert ts.endswith("Z"), "Timestamp must end with Z"
        assert "T" in ts, "Timestamp must be ISO-8601"


# ===========================================================================
# 3. Stethoscope MQTT ASSIGN_VISIT handling
# ===========================================================================


class TestStethoscopeAssignVisit:
    def test_valid_assign_visit_runs_once_and_uses_command_visit_id(
        self, tmp_path: Path
    ) -> None:
        from simulators.stethoscope.simulator import StethoscopeSimulator

        simulator = StethoscopeSimulator(write_wav(tmp_path))
        simulator._simulate_recording = MagicMock()  # type: ignore[method-assign]
        command = {
            "version": 1,
            "type": "ASSIGN_VISIT",
            "messageId": str(uuid.uuid4()),
            "visitId": str(uuid.uuid4()),
            "timestamp": "2026-10-08T15:30:00.000Z",
        }

        simulator._handle_command("respicare/device/RESPICARE-STETH-001/command", command)
        simulator._handle_command("respicare/device/RESPICARE-STETH-001/command", command)

        simulator._simulate_recording.assert_called_once_with(command["visitId"])
        assert simulator._current_visit_id == command["visitId"]

    def test_invalid_assign_visit_is_ignored(self, tmp_path: Path) -> None:
        from simulators.stethoscope.simulator import StethoscopeSimulator

        simulator = StethoscopeSimulator(write_wav(tmp_path))
        simulator._simulate_recording = MagicMock()  # type: ignore[method-assign]

        simulator._handle_command(
            "respicare/device/RESPICARE-STETH-001/command",
            {"type": "ASSIGN_VISIT", "visitId": str(uuid.uuid4())},
        )

        simulator._simulate_recording.assert_not_called()


# ===========================================================================
# 4. MQTT topic generation
# ===========================================================================


class TestMqttTopicGeneration:
    def test_command_topic(self) -> None:
        from common.models import mqtt_topic

        assert mqtt_topic("RESPICARE-STETH-001", "command") == \
               "respicare/device/RESPICARE-STETH-001/command"

    def test_event_topic(self) -> None:
        from common.models import mqtt_topic

        assert mqtt_topic("RESPICARE-STETH-001", "event") == \
               "respicare/device/RESPICARE-STETH-001/event"

    def test_status_topic(self) -> None:
        from common.models import mqtt_topic

        assert mqtt_topic("RESPICARE-SPO2-001", "status") == \
               "respicare/device/RESPICARE-SPO2-001/status"


# ===========================================================================
# 5. MQTT TLS configuration
# ===========================================================================


class TestMqttTlsConfiguration:
    def test_settings_accepts_mqtt_ca_cert(self) -> None:
        from common.config import Settings

        configured = Settings(mqtt_ca_cert="/tmp/respicare-mqtt-ca.crt")

        assert configured.mqtt_ca_cert == Path("/tmp/respicare-mqtt-ca.crt")

    @patch("common.mqtt_client.mqtt.Client")
    def test_private_ca_enables_verified_tls(self, mock_client_cls: MagicMock) -> None:
        from common.mqtt_client import MqttClient

        MqttClient(
            device_id="RESPICARE-STETH-001",
            ca_cert="/tmp/respicare-mqtt-ca.crt",
        )

        mqtt_client = mock_client_cls.return_value
        mqtt_client.tls_set.assert_called_once_with(
            ca_certs="/tmp/respicare-mqtt-ca.crt"
        )
        mqtt_client.tls_insecure_set.assert_not_called()

    @patch("common.mqtt_client.mqtt.Client")
    def test_no_ca_keeps_plain_local_mqtt(self, mock_client_cls: MagicMock) -> None:
        from common.mqtt_client import MqttClient

        with patch("common.mqtt_client.settings.mqtt_ca_cert", None):
            MqttClient(device_id="RESPICARE-STETH-001")

        mock_client_cls.return_value.tls_set.assert_not_called()


# ===========================================================================
# 6. WAV metadata validation
# ===========================================================================


class TestWavValidation:
    def test_valid_wav_passes(self, tmp_path: Path) -> None:
        from common.wav_utils import validate_wav

        p = write_wav(tmp_path)
        meta = validate_wav(p)
        assert meta.channels == 1
        assert meta.sample_rate == 16000
        assert meta.sample_width_bits == 16

    def test_duration_calculation(self, tmp_path: Path) -> None:
        from common.wav_utils import validate_wav

        # 16000 frames at 16000 Hz → exactly 1 second
        p = write_wav(tmp_path, n_frames=16000)
        meta = validate_wav(p)
        assert abs(meta.duration_seconds - 1.0) < 0.01

    def test_wrong_sample_rate_raises(self, tmp_path: Path) -> None:
        from common.wav_utils import WavValidationError, validate_wav

        p = write_wav(tmp_path, sample_rate=44100)
        with pytest.raises(WavValidationError, match="sample rate"):
            validate_wav(p)

    def test_wrong_channels_raises(self, tmp_path: Path) -> None:
        from common.wav_utils import WavValidationError, validate_wav

        p = write_wav(tmp_path, channels=2)
        with pytest.raises(WavValidationError, match="channels"):
            validate_wav(p)

    def test_wrong_sample_width_raises(self, tmp_path: Path) -> None:
        from common.wav_utils import WavValidationError, validate_wav

        p = write_wav(tmp_path, sample_width=1)  # 8-bit
        with pytest.raises(WavValidationError, match="sample width"):
            validate_wav(p)

    def test_multiple_errors_reported(self, tmp_path: Path) -> None:
        from common.wav_utils import WavValidationError, validate_wav

        p = write_wav(tmp_path, channels=2, sample_rate=44100)
        with pytest.raises(WavValidationError) as exc_info:
            validate_wav(p)
        msg = str(exc_info.value)
        assert "channels" in msg
        assert "sample rate" in msg

    def test_missing_file_raises(self, tmp_path: Path) -> None:
        from common.wav_utils import validate_wav

        with pytest.raises(FileNotFoundError):
            validate_wav(tmp_path / "nonexistent.wav")

    def test_invalid_wav_bytes_raises(self, tmp_path: Path) -> None:
        from common.wav_utils import WavValidationError, read_wav_metadata

        p = tmp_path / "bad.wav"
        p.write_bytes(b"this is not a wav file at all")
        with pytest.raises(WavValidationError):
            read_wav_metadata(p)


# ===========================================================================
# 5. Upload-URL response parsing (http_client)
# ===========================================================================


class TestUploadUrlResponseParsing:
    def _mock_response(self, body: dict, status_code: int = 200) -> MagicMock:
        resp = MagicMock()
        resp.status_code = status_code
        resp.json.return_value = body
        resp.text = json.dumps(body)
        return resp

    @patch("common.http_client.httpx.Client")
    def test_parses_recording_id_and_upload_url(self, mock_client_cls: MagicMock) -> None:
        from common.http_client import request_upload_url

        mock_resp = self._mock_response({
            "recordingId": "rec-001",
            "uploadUrl": "https://storage.example.com/signed",
        })
        mock_client_cls.return_value.__enter__.return_value.post.return_value = mock_resp

        result = request_upload_url("visit-001")
        assert result.recording_id == "rec-001"
        assert result.upload_url == "https://storage.example.com/signed"

    @patch("common.http_client.httpx.Client")
    def test_accepts_snake_case_keys(self, mock_client_cls: MagicMock) -> None:
        from common.http_client import request_upload_url

        mock_resp = self._mock_response({
            "recording_id": "rec-002",
            "upload_url": "https://storage.example.com/signed2",
        })
        mock_client_cls.return_value.__enter__.return_value.post.return_value = mock_resp

        result = request_upload_url("visit-002")
        assert result.recording_id == "rec-002"

    @patch("common.http_client.httpx.Client")
    def test_raises_on_401(self, mock_client_cls: MagicMock) -> None:
        from common.http_client import WebClientError, request_upload_url

        mock_resp = MagicMock()
        mock_resp.status_code = 401
        mock_resp.text = "Unauthorized"
        mock_client_cls.return_value.__enter__.return_value.post.return_value = mock_resp

        with pytest.raises(WebClientError, match="401"):
            request_upload_url("visit-x")

    @patch("common.http_client.httpx.Client")
    def test_raises_on_404(self, mock_client_cls: MagicMock) -> None:
        from common.http_client import WebClientError, request_upload_url

        mock_resp = MagicMock()
        mock_resp.status_code = 404
        mock_resp.text = "Not Found"
        mock_client_cls.return_value.__enter__.return_value.post.return_value = mock_resp

        with pytest.raises(WebClientError, match="404"):
            request_upload_url("visit-missing")

    @patch("common.http_client.httpx.Client")
    def test_raises_when_keys_missing(self, mock_client_cls: MagicMock) -> None:
        from common.http_client import WebClientError, request_upload_url

        mock_resp = self._mock_response({"something": "unexpected"})
        mock_client_cls.return_value.__enter__.return_value.post.return_value = mock_resp

        with pytest.raises(WebClientError, match="recordingId"):
            request_upload_url("visit-bad")


# ===========================================================================
# 6. Upload failure handling
# ===========================================================================


class TestUploadFailure:
    @patch("common.http_client.httpx.Client")
    def test_storage_403_raises_web_client_error(self, mock_client_cls: MagicMock, tmp_path: Path) -> None:
        from common.http_client import WebClientError, upload_wav_to_storage

        mock_resp = MagicMock()
        mock_resp.status_code = 403
        mock_resp.text = "Forbidden"
        mock_client_cls.return_value.__enter__.return_value.put.return_value = mock_resp

        p = write_wav(tmp_path)
        with pytest.raises(WebClientError, match="403"):
            upload_wav_to_storage("https://storage.example.com/expired", p)

    @patch("common.http_client.httpx.Client")
    def test_storage_500_raises_web_client_error(self, mock_client_cls: MagicMock, tmp_path: Path) -> None:
        from common.http_client import WebClientError, upload_wav_to_storage

        mock_resp = MagicMock()
        mock_resp.status_code = 500
        mock_resp.text = "Internal Server Error"
        mock_client_cls.return_value.__enter__.return_value.put.return_value = mock_resp

        p = write_wav(tmp_path)
        with pytest.raises(WebClientError, match="500"):
            upload_wav_to_storage("https://storage.example.com/signed", p)


# ===========================================================================
# 7. Complete recording failure handling
# ===========================================================================


class TestCompleteFailure:
    @patch("common.http_client.httpx.Client")
    def test_complete_401_raises(self, mock_client_cls: MagicMock) -> None:
        from common.http_client import WebClientError, complete_recording

        mock_resp = MagicMock()
        mock_resp.status_code = 401
        mock_resp.text = "Unauthorized"
        mock_client_cls.return_value.__enter__.return_value.post.return_value = mock_resp

        with pytest.raises(WebClientError, match="401"):
            complete_recording("rec-abc")

    @patch("common.http_client.httpx.Client")
    def test_complete_404_raises(self, mock_client_cls: MagicMock) -> None:
        from common.http_client import WebClientError, complete_recording

        mock_resp = MagicMock()
        mock_resp.status_code = 404
        mock_resp.text = "Not Found"
        mock_client_cls.return_value.__enter__.return_value.post.return_value = mock_resp

        with pytest.raises(WebClientError, match="404"):
            complete_recording("rec-missing")


# ===========================================================================
# 8. Successful simulated firmware flow (mocked HTTP + MQTT)
# ===========================================================================


class TestSuccessfulSimulatedFlow:
    def _make_mock_mqtt(self) -> MagicMock:
        """Create a MqttClient mock that tracks published events."""
        m = MagicMock()
        m.device_id = "RESPICARE-STETH-001"
        return m

    @patch("common.http_client.httpx.Client")
    def test_full_upload_flow_success(
        self, mock_client_cls: MagicMock, tmp_path: Path
    ) -> None:
        from simulators.stethoscope.client import StethoscopeClient

        # Arrange WAV
        wav_path = write_wav(tmp_path)

        # Arrange HTTP responses
        post_upload_url_resp = MagicMock()
        post_upload_url_resp.status_code = 200
        post_upload_url_resp.json.return_value = {
            "recordingId": "rec-999",
            "uploadUrl": "https://storage.example.com/signed-url",
        }

        put_resp = MagicMock()
        put_resp.status_code = 200
        put_resp.text = ""

        post_complete_resp = MagicMock()
        post_complete_resp.status_code = 200
        post_complete_resp.json.return_value = {"status": "analyzing"}

        http_context = mock_client_cls.return_value.__enter__.return_value
        http_context.post.side_effect = [post_upload_url_resp, post_complete_resp]
        http_context.put.return_value = put_resp

        # Arrange MQTT mock
        mock_mqtt = self._make_mock_mqtt()

        # Act
        client = StethoscopeClient(mock_mqtt)
        success = client.run_upload_flow(visit_id="visit-123", wav_path=wav_path)

        # Assert flow succeeded
        assert success is True

        # Assert correct sequence of MQTT events was published
        publish_calls = mock_mqtt.publish_event.call_args_list
        event_types = [call.args[0].type for call in publish_calls]
        assert "UPLOAD_STARTED" in event_types
        assert "UPLOAD_SUCCESS" in event_types
        assert "UPLOAD_FAILED" not in event_types

    @patch("common.http_client.httpx.Client")
    def test_wav_validation_failure_publishes_upload_failed(
        self, mock_client_cls: MagicMock, tmp_path: Path
    ) -> None:
        from simulators.stethoscope.client import StethoscopeClient

        # Wrong format WAV
        wav_path = write_wav(tmp_path, channels=2, sample_rate=44100)

        mock_mqtt = self._make_mock_mqtt()
        client = StethoscopeClient(mock_mqtt)
        success = client.run_upload_flow(visit_id="visit-456", wav_path=wav_path)

        assert success is False
        publish_calls = mock_mqtt.publish_event.call_args_list
        event_types = [call.args[0].type for call in publish_calls]
        assert "UPLOAD_FAILED" in event_types

    @patch("common.http_client.httpx.Client")
    def test_upload_url_failure_publishes_upload_failed(
        self, mock_client_cls: MagicMock, tmp_path: Path
    ) -> None:
        from simulators.stethoscope.client import StethoscopeClient

        wav_path = write_wav(tmp_path)

        mock_resp = MagicMock()
        mock_resp.status_code = 404
        mock_resp.text = "Visit not found"
        http_context = mock_client_cls.return_value.__enter__.return_value
        http_context.post.return_value = mock_resp

        mock_mqtt = self._make_mock_mqtt()
        client = StethoscopeClient(mock_mqtt)
        success = client.run_upload_flow(visit_id="visit-bad", wav_path=wav_path)

        assert success is False
        publish_calls = mock_mqtt.publish_event.call_args_list
        event_types = [call.args[0].type for call in publish_calls]
        assert "UPLOAD_FAILED" in event_types

    @patch("common.http_client.httpx.Client")
    def test_complete_failure_publishes_upload_failed(
        self, mock_client_cls: MagicMock, tmp_path: Path
    ) -> None:
        from simulators.stethoscope.client import StethoscopeClient

        wav_path = write_wav(tmp_path)

        upload_url_resp = MagicMock()
        upload_url_resp.status_code = 200
        upload_url_resp.json.return_value = {
            "recordingId": "rec-999",
            "uploadUrl": "https://storage.example.com/signed-url",
        }

        put_resp = MagicMock()
        put_resp.status_code = 200

        complete_resp = MagicMock()
        complete_resp.status_code = 500
        complete_resp.text = "Internal Server Error"

        http_context = mock_client_cls.return_value.__enter__.return_value
        http_context.post.side_effect = [upload_url_resp, complete_resp]
        http_context.put.return_value = put_resp

        mock_mqtt = self._make_mock_mqtt()
        client = StethoscopeClient(mock_mqtt)
        success = client.run_upload_flow(visit_id="visit-789", wav_path=wav_path)

        assert success is False
        publish_calls = mock_mqtt.publish_event.call_args_list
        event_types = [call.args[0].type for call in publish_calls]
        assert "UPLOAD_FAILED" in event_types
        assert "UPLOAD_STARTED" in event_types  # started was published before failure
