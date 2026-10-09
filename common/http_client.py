"""
HTTP client for communicating with the RespiCare web backend.

Handles:
  - Requesting a signed Supabase upload URL from the web backend
  - Uploading the WAV binary directly to the signed Supabase Storage URL
  - Calling the recording-complete endpoint

The simulator never calls the AI server directly.
All AI analysis is triggered server-side after the complete endpoint succeeds.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from common.config import settings

logger = logging.getLogger(__name__)

# Seconds to wait for web backend responses.
_WEB_TIMEOUT = 30.0

# Seconds to wait for Supabase Storage PUT.
_STORAGE_TIMEOUT = 120.0


@dataclass
class UploadUrlResponse:
    """Parsed response from POST /api/device/visits/{visitId}/recording/upload-url."""

    recording_id: str
    upload_url: str


class WebClientError(RuntimeError):
    """Raised for non-recoverable web/backend communication errors."""


def _safe_url_snippet(url: str, max_chars: int = 60) -> str:
    """
    Return a truncated URL safe to log.

    Signed URL tokens must not be logged in full.
    """
    return url[:max_chars] + "…" if len(url) > max_chars else url


def request_upload_url(visit_id: str) -> UploadUrlResponse:
    """
    Request a signed Supabase Storage upload URL.

    POST /api/device/visits/{visitId}/recording/upload-url

    Returns:
        UploadUrlResponse containing:
        - recording_id
        - upload_url

    Raises:
        WebClientError: For invalid responses or HTTP errors.
        httpx.HTTPError: For network-level failures.
    """
    url = settings.upload_url_endpoint(visit_id)

    logger.info("Requesting upload URL from %s", url)

    with httpx.Client(timeout=_WEB_TIMEOUT) as client:
        response = client.post(
            url,
            headers=settings.device_headers(),
            json={},
        )

    if response.status_code == 401:
        raise WebClientError(
            "Invalid device API key (HTTP 401). " "Check DEVICE_API_KEY in .env."
        )

    if response.status_code == 404:
        raise WebClientError(f"Visit '{visit_id}' not found on web backend (HTTP 404).")

    if response.status_code >= 400:
        raise WebClientError(
            f"Upload-URL request failed with HTTP "
            f"{response.status_code}: {response.text[:200]}"
        )

    try:
        body: dict[str, Any] = response.json()
    except Exception as exc:
        raise WebClientError("Upload-URL endpoint returned invalid JSON.") from exc

    # Current RespiCare API wraps successful responses in:
    #
    # {
    #   "data": {
    #       "recording_id": "...",
    #       "upload_url": "...",
    #       ...
    #   }
    # }
    #
    # Keep fallback support for non-wrapped responses.
    data = body.get("data", body)

    if not isinstance(data, dict):
        raise WebClientError(
            "Invalid upload-url response: expected an object in 'data'."
        )

    recording_id = (
        data.get("recording_id")
        or data.get("recordingId")
        or data.get("id")
        or (
            data.get("recording", {}).get("id")
            if isinstance(data.get("recording"), dict)
            else None
        )
    )

    upload_url = (
        data.get("upload_url")
        or data.get("uploadUrl")
        or data.get("signed_url")
        or data.get("signedUrl")
        or data.get("url")
    )

    if not recording_id or not upload_url:
        raise WebClientError(
            "Could not extract recordingId/uploadUrl from response. "
            f"Top-level keys: {list(body.keys())}, "
            f"data keys: {list(data.keys())}"
        )

    logger.info(
        "Got recordingId=%s, uploadUrl=%s",
        recording_id,
        _safe_url_snippet(str(upload_url)),
    )

    return UploadUrlResponse(
        recording_id=str(recording_id),
        upload_url=str(upload_url),
    )


def upload_wav_to_storage(
    signed_url: str,
    wav_path: Path,
) -> None:
    """
    Upload WAV binary directly to the signed Supabase Storage URL.

    Uses:
        Content-Type: audio/wav

    Raises:
        WebClientError: For rejected or failed uploads.
        httpx.HTTPError: For network-level failures.
    """
    if not wav_path.exists():
        raise WebClientError(f"WAV file does not exist: {wav_path}")

    if not wav_path.is_file():
        raise WebClientError(f"WAV path is not a file: {wav_path}")

    file_size = wav_path.stat().st_size

    logger.info(
        "Uploading WAV '%s' (%d bytes) to storage: %s",
        wav_path.name,
        file_size,
        _safe_url_snippet(signed_url),
    )

    with wav_path.open("rb") as fh:
        wav_bytes = fh.read()

    with httpx.Client(timeout=_STORAGE_TIMEOUT) as client:
        response = client.put(
            signed_url,
            content=wav_bytes,
            headers={
                "Content-Type": "audio/wav",
            },
        )

    if response.status_code in (400, 403):
        raise WebClientError(
            f"Storage upload rejected (HTTP {response.status_code}). "
            "The signed URL may be expired or malformed."
        )

    if response.status_code >= 400:
        raise WebClientError(
            f"Storage upload failed with HTTP "
            f"{response.status_code}: {response.text[:200]}"
        )

    logger.info(
        "WAV upload to storage succeeded (HTTP %d).",
        response.status_code,
    )


def complete_recording(
    recording_id: str,
) -> dict[str, Any]:
    """
    Notify the web backend that the WAV upload is complete.

    POST /api/device/recordings/{recordingId}/complete

    Important:
        The backend expects a valid JSON body, even when there are
        currently no fields required. Therefore json={} must be sent.

    After this endpoint succeeds, the web backend is responsible for:
        - validating the uploaded WAV
        - marking the recording as uploaded
        - triggering AI analysis
        - persisting respiratory cycles/results

    The simulator must never call the AI server directly.

    Returns:
        Parsed JSON response when available.

    Raises:
        WebClientError: For HTTP/client errors.
        httpx.HTTPError: For network-level failures.
    """
    url = settings.complete_endpoint(recording_id)

    logger.info(
        "Calling recording complete endpoint: %s",
        url,
    )

    with httpx.Client(timeout=_WEB_TIMEOUT) as client:
        response = client.post(
            url,
            headers=settings.device_headers(),
            json={},
        )

    if response.status_code == 401:
        raise WebClientError(
            "Invalid device API key (HTTP 401). " "Check DEVICE_API_KEY in .env."
        )

    if response.status_code == 404:
        raise WebClientError(
            f"Recording '{recording_id}' not found " "on web backend (HTTP 404)."
        )

    if response.status_code >= 400:
        raise WebClientError(
            f"Complete endpoint failed with HTTP "
            f"{response.status_code}: {response.text[:200]}"
        )

    body: dict[str, Any] = {}

    try:
        parsed = response.json()

        if isinstance(parsed, dict):
            body = parsed
    except Exception:
        # Some successful endpoints may return an empty body.
        pass

    logger.info(
        "Recording complete acknowledged (HTTP %d). "
        "AI analysis will be triggered by the web backend.",
        response.status_code,
    )

    return body
