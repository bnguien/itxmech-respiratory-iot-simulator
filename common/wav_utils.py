"""
WAV file validation and metadata utilities.

The real RespiCare stethoscope firmware produces WAV files with a fixed format.
This module validates that any supplied file matches those requirements before
the simulator attempts an upload.

Expected format:
  - PCM encoding
  - mono (1 channel)
  - 16-bit (sample width = 2 bytes)
  - 16 kHz sample rate
"""

from __future__ import annotations

import logging
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from common.config import settings

logger = logging.getLogger(__name__)


@dataclass
class WavMetadata:
    """Metadata extracted from a WAV file header."""

    path: Path
    channels: int
    sample_rate: int
    sample_width_bytes: int
    n_frames: int

    @property
    def sample_width_bits(self) -> int:
        return self.sample_width_bytes * 8

    @property
    def duration_seconds(self) -> float:
        if self.sample_rate == 0:
            return 0.0
        return self.n_frames / self.sample_rate

    def __str__(self) -> str:
        return (
            f"WAV({self.path.name}: "
            f"{self.channels}ch, "
            f"{self.sample_rate} Hz, "
            f"{self.sample_width_bits}-bit, "
            f"{self.duration_seconds:.1f}s)"
        )


class WavValidationError(ValueError):
    """Raised when a WAV file does not meet RespiCare firmware requirements."""


def read_wav_metadata(path: Path) -> WavMetadata:
    """
    Open the WAV file and extract its header metadata.

    Raises:
        FileNotFoundError: If the file does not exist.
        WavValidationError: If the file cannot be read as a WAV.
    """
    if not path.exists():
        raise FileNotFoundError(f"WAV file not found: {path}")

    try:
        with wave.open(str(path), "rb") as wf:
            return WavMetadata(
                path=path,
                channels=wf.getnchannels(),
                sample_rate=wf.getframerate(),
                sample_width_bytes=wf.getsampwidth(),
                n_frames=wf.getnframes(),
            )
    except wave.Error as exc:
        raise WavValidationError(f"Cannot read WAV file '{path}': {exc}") from exc
    except EOFError as exc:
        raise WavValidationError(f"WAV file '{path}' appears to be empty or truncated.") from exc


def validate_wav(path: Path) -> WavMetadata:
    """
    Validate a WAV file against RespiCare's expected format.

    Logs a summary of the file's metadata and raises WavValidationError
    if the format does not match expectations.

    Returns:
        WavMetadata for the validated file.

    Raises:
        FileNotFoundError: If the file does not exist.
        WavValidationError: If the format is wrong.
    """
    meta = read_wav_metadata(path)
    logger.info("WAV metadata: %s", meta)

    errors: list[str] = []

    if meta.channels != settings.wav_expected_channels:
        errors.append(
            f"channels: got {meta.channels}, expected {settings.wav_expected_channels} (mono)"
        )

    if meta.sample_rate != settings.wav_expected_sample_rate:
        errors.append(
            f"sample rate: got {meta.sample_rate} Hz, "
            f"expected {settings.wav_expected_sample_rate} Hz"
        )

    if meta.sample_width_bytes != settings.wav_expected_sample_width:
        errors.append(
            f"sample width: got {meta.sample_width_bits}-bit, "
            f"expected {settings.wav_expected_sample_width * 8}-bit"
        )

    if errors:
        msg = (
            f"WAV file '{path.name}' does not meet RespiCare firmware requirements:\n"
            + "\n".join(f"  • {e}" for e in errors)
            + "\n\nRequired: PCM, mono, 16-bit, 16 kHz."
        )
        raise WavValidationError(msg)

    logger.info(
        "WAV validation passed: %s (%.1f seconds)", path.name, meta.duration_seconds
    )
    return meta
