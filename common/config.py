"""
Configuration for the RespiCare IoT Simulator.

Loads settings from environment variables or a .env file in the project root.
All secrets (API keys, passwords) are read at runtime and never committed.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Central configuration loaded from environment / .env file."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ------------------------------------------------------------------
    # Web backend
    # ------------------------------------------------------------------
    web_base_url: str = Field(
        default="http://localhost:3000",
        description="Base URL of the RespiCare Next.js web backend.",
    )

    # ------------------------------------------------------------------
    # Device identity
    # ------------------------------------------------------------------
    device_api_key: str = Field(
        default="",
        description="Shared device API key sent as X-Device-Key header.",
    )
    stethoscope_device_id: str = Field(
        default="RESPICARE-STETH-001",
        description="Device ID for the electronic stethoscope simulator.",
    )
    spo2_device_id: str = Field(
        default="RESPICARE-SPO2-001",
        description="Device ID for the SpO2 wearable simulator.",
    )

    # ------------------------------------------------------------------
    # MQTT broker
    # ------------------------------------------------------------------
    mqtt_host: str = Field(default="localhost", description="MQTT broker hostname.")
    mqtt_port: int = Field(default=1883, description="MQTT broker port.")
    mqtt_username: Optional[str] = Field(
        default=None, description="MQTT username (optional for local dev)."
    )
    mqtt_password: Optional[str] = Field(
        default=None, description="MQTT password (optional for local dev)."
    )
    mqtt_ca_cert: Optional[Path] = Field(
        default=None,
        description=(
            "Path to the CA certificate used to verify a TLS MQTT broker. "
            "When unset, MQTT uses a plain TCP connection."
        ),
    )

    # ------------------------------------------------------------------
    # Simulator behaviour
    # ------------------------------------------------------------------
    recording_delay_seconds: float = Field(
        default=3.0,
        description="Simulated auscultation duration in seconds (configurable).",
    )
    default_wav_path: Optional[Path] = Field(
        default=None,
        description="Default WAV file to use when none is supplied via CLI.",
    )

    # ------------------------------------------------------------------
    # WAV format requirements (must match backend expectations)
    # ------------------------------------------------------------------
    wav_expected_channels: int = Field(default=1, description="Expected channels (mono=1).")
    wav_expected_sample_rate: int = Field(default=16000, description="Expected sample rate Hz.")
    wav_expected_sample_width: int = Field(default=2, description="Expected sample width bytes (16-bit=2).")

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def upload_url_endpoint(self, visit_id: str) -> str:
        return f"{self.web_base_url}/api/device/visits/{visit_id}/recording/upload-url"

    def complete_endpoint(self, recording_id: str) -> str:
        return f"{self.web_base_url}/api/device/recordings/{recording_id}/complete"

    def device_headers(self) -> dict[str, str]:
        return {"X-Device-Key": self.device_api_key}


# Singleton – import and use `settings` directly throughout the project.
settings = Settings()
