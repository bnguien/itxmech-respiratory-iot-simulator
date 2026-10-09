"""
Stethoscope client: performs the full upload flow for one visit.

This module isolates the HTTP + MQTT coordination logic so it can be
reused by both the interactive simulator and the full-flow script.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from common.http_client import (
    WebClientError,
    complete_recording,
    request_upload_url,
    upload_wav_to_storage,
)
from common.models import (
    UploadFailedEvent,
    UploadStartedEvent,
    UploadSuccessEvent,
)
from common.mqtt_client import MqttClient
from common.wav_utils import WavValidationError, validate_wav

logger = logging.getLogger(__name__)


class StethoscopeClient:
    """
    Orchestrates the WAV upload flow for a single visit.

    1. Validate WAV format
    2. Request signed upload URL from web backend
    3. PUT WAV to Supabase Storage
    4. Call recording-complete endpoint
    5. Publish UPLOAD_SUCCESS or UPLOAD_FAILED via MQTT
    """

    def __init__(self, mqtt: MqttClient) -> None:
        self._mqtt = mqtt

    def run_upload_flow(
        self,
        visit_id: str,
        wav_path: Path,
    ) -> bool:
        """
        Execute the full upload flow.

        Returns True on success, False on any failure.
        MQTT events are published at each step.
        """
        device_id = self._mqtt.device_id
        recording_id: Optional[str] = None

        try:
            # ----------------------------------------------------------------
            # Step 0: Validate WAV format before touching the network.
            # ----------------------------------------------------------------
            validate_wav(wav_path)

            # ----------------------------------------------------------------
            # Step 1: Request signed upload URL
            # ----------------------------------------------------------------
            upload_url_resp = request_upload_url(visit_id)
            recording_id = upload_url_resp.recording_id

            # ----------------------------------------------------------------
            # Step 2: Publish UPLOAD_STARTED
            # ----------------------------------------------------------------
            self._mqtt.publish_event(
                UploadStartedEvent(
                    device_id=device_id,
                    visit_id=visit_id,
                    recording_id=recording_id,
                )
            )

            # ----------------------------------------------------------------
            # Step 3: PUT WAV to Supabase Storage
            # ----------------------------------------------------------------
            upload_wav_to_storage(upload_url_resp.upload_url, wav_path)

            # ----------------------------------------------------------------
            # Step 4: Call complete endpoint
            # ----------------------------------------------------------------
            complete_recording(recording_id)

            # ----------------------------------------------------------------
            # Step 5: Publish UPLOAD_SUCCESS
            # ----------------------------------------------------------------
            self._mqtt.publish_event(
                UploadSuccessEvent(
                    device_id=device_id,
                    visit_id=visit_id,
                    recording_id=recording_id,
                )
            )
            logger.info(
                "Upload flow complete. Visit=%s Recording=%s. "
                "Web backend will trigger AI analysis.",
                visit_id,
                recording_id,
            )
            return True

        except WavValidationError as exc:
            logger.error("WAV validation failed: %s", exc)
            self._publish_failed(device_id, visit_id, recording_id, str(exc))
            return False

        except WebClientError as exc:
            logger.error("Web backend error: %s", exc)
            self._publish_failed(device_id, visit_id, recording_id, str(exc))
            return False

        except Exception as exc:
            logger.error("Unexpected error during upload flow: %s", exc)
            self._publish_failed(device_id, visit_id, recording_id, "Internal simulator error.")
            return False

    def _publish_failed(
        self,
        device_id: str,
        visit_id: str,
        recording_id: Optional[str],
        error: str,
    ) -> None:
        try:
            self._mqtt.publish_event(
                UploadFailedEvent(
                    device_id=device_id,
                    visit_id=visit_id,
                    recording_id=recording_id,
                    error=error,
                )
            )
        except Exception as pub_exc:
            logger.warning("Could not publish UPLOAD_FAILED event: %s", pub_exc)
