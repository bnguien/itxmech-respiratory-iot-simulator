"""
Typed Pydantic models for all MQTT message payloads.

These models define the canonical wire format for RespiCare device communication.
Both the simulator and the real firmware should serialise/deserialise using this schema.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def new_message_id() -> str:
    """Generate a new UUID4 string for use as a messageId."""
    return str(uuid.uuid4())


def utc_now() -> str:
    """Return the current UTC time formatted as ISO-8601 with 'Z' suffix."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def mqtt_topic(device_id: str, channel: Literal["command", "event", "status"]) -> str:
    """Build the canonical MQTT topic for a device channel."""
    return f"respicare/device/{device_id}/{channel}"


# ---------------------------------------------------------------------------
# Base message
# ---------------------------------------------------------------------------


class BaseMessage(BaseModel):
    """Fields present in every RespiCare MQTT message."""

    version: int = 1
    type: str
    message_id: str = Field(default_factory=new_message_id, alias="messageId")
    device_id: Optional[str] = Field(default=None, alias="deviceId")
    visit_id: Optional[str] = Field(default=None, alias="visitId")
    timestamp: str = Field(default_factory=utc_now)

    model_config = {"populate_by_name": True}

    def to_json(self) -> str:
        """Serialise to JSON using aliased field names (camelCase on the wire)."""
        return self.model_dump_json(by_alias=True, exclude_none=True)

    @classmethod
    def from_json(cls, data: str | bytes) -> "BaseMessage":
        return cls.model_validate_json(data)


# ---------------------------------------------------------------------------
# Commands (web → device)
# ---------------------------------------------------------------------------


class AssignVisitCommand(BaseMessage):
    """ASSIGN_VISIT command sent from the web backend to the stethoscope."""

    type: Literal["ASSIGN_VISIT"] = "ASSIGN_VISIT"
    # visit_id is inherited from BaseMessage and carries the assigned visit UUID


# ---------------------------------------------------------------------------
# Stethoscope events (device → web)
# ---------------------------------------------------------------------------


class VisitAssignedEvent(BaseMessage):
    """Confirms the device has accepted the visit assignment."""

    type: Literal["VISIT_ASSIGNED"] = "VISIT_ASSIGNED"


class RecordingStartedEvent(BaseMessage):
    """Published immediately before simulated auscultation begins."""

    type: Literal["RECORDING_STARTED"] = "RECORDING_STARTED"


class RecordingStoppedEvent(BaseMessage):
    """Published when simulated auscultation is complete."""

    type: Literal["RECORDING_STOPPED"] = "RECORDING_STOPPED"


class UploadStartedEvent(BaseMessage):
    """Published just before the WAV file upload begins."""

    type: Literal["UPLOAD_STARTED"] = "UPLOAD_STARTED"
    recording_id: Optional[str] = Field(default=None, alias="recordingId")


class UploadSuccessEvent(BaseMessage):
    """Published after the web backend's complete endpoint returns success."""

    type: Literal["UPLOAD_SUCCESS"] = "UPLOAD_SUCCESS"
    recording_id: Optional[str] = Field(default=None, alias="recordingId")


class UploadFailedEvent(BaseMessage):
    """Published when any upload step (URL request, PUT, or complete) fails."""

    type: Literal["UPLOAD_FAILED"] = "UPLOAD_FAILED"
    recording_id: Optional[str] = Field(default=None, alias="recordingId")
    error: Optional[str] = Field(default=None)


# ---------------------------------------------------------------------------
# Device status (retained, with Last Will)
# ---------------------------------------------------------------------------


class DeviceStatusMessage(BaseMessage):
    """
    Device presence status message.
    Always published as a retained message so new subscribers see current state.
    DEVICE_OFFLINE is also configured as the MQTT Last Will.
    """

    type: Literal["DEVICE_ONLINE", "DEVICE_OFFLINE"]


# ---------------------------------------------------------------------------
# SpO2 events
# ---------------------------------------------------------------------------


class Spo2ReadingEvent(BaseMessage):
    """Real-time SpO2 reading published by the wearable simulator."""

    type: Literal["SPO2_READING"] = "SPO2_READING"
    spo2: int = Field(..., ge=0, le=100, description="SpO2 percentage (0–100).")


# ---------------------------------------------------------------------------
# Convenience: parse any incoming command payload
# ---------------------------------------------------------------------------


def parse_command(payload: str | bytes) -> dict[str, Any]:
    """Parse an incoming JSON command payload into a plain dict."""
    import json

    if isinstance(payload, bytes):
        payload = payload.decode("utf-8")
    return json.loads(payload)
