"""
Electronic stethoscope device simulator.

Supports two modes of operation:

1. CLI mode (--visit-id):
   Immediately runs the full simulation for the given visit.

2. MQTT listen mode (no --visit-id):
   Waits for an ASSIGN_VISIT command on the device command topic,
   then automatically runs the simulation.

Usage:
    # Direct visit assignment:
    python -m simulators.stethoscope.simulator \\
        --visit-id <UUID> \\
        --wav /path/to/test-16k-mono.wav

    # MQTT listen mode (waits for ASSIGN_VISIT command):
    python -m simulators.stethoscope.simulator \\
        --wav /path/to/test-16k-mono.wav
"""

from __future__ import annotations

import argparse
import logging
import signal
import sys
import time
from pathlib import Path
from typing import Optional

from common.config import settings
from common.models import (
    RecordingStartedEvent,
    RecordingStoppedEvent,
    VisitAssignedEvent,
)
from common.mqtt_client import MqttClient
from simulators.stethoscope.client import StethoscopeClient

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
logger = logging.getLogger(__name__)


class StethoscopeSimulator:
    """
    Simulates a RespiCare electronic stethoscope device.

    Does NOT capture real audio. Instead it uses a pre-recorded WAV file
    supplied via CLI or config to simulate the recording the real firmware
    would produce during an auscultation session.
    """

    def __init__(self, wav_path: Path) -> None:
        self._wav_path = wav_path
        self._current_visit_id: Optional[str] = None
        self._running = False

        device_id = settings.stethoscope_device_id

        self._mqtt = MqttClient(
            device_id=device_id,
            on_command=self._handle_command,
        )
        self._client = StethoscopeClient(self._mqtt)

    # ------------------------------------------------------------------
    # Public entry points
    # ------------------------------------------------------------------

    def run_with_visit(self, visit_id: str) -> None:
        """CLI mode: connect, run simulation for a known visit, disconnect."""
        logger.info(
            "=== Stethoscope Simulator (CLI mode) ===\n"
            "  Device ID : %s\n"
            "  Visit ID  : %s\n"
            "  WAV file  : %s",
            settings.stethoscope_device_id,
            visit_id,
            self._wav_path,
        )
        self._mqtt.connect()
        try:
            self._simulate_recording(visit_id)
        finally:
            self._mqtt.disconnect()

    def run_listen_mode(self) -> None:
        """
        MQTT listen mode: wait for ASSIGN_VISIT command, then run simulation.
        Ctrl-C to exit.
        """
        logger.info(
            "=== Stethoscope Simulator (MQTT listen mode) ===\n"
            "  Device ID : %s\n"
            "  WAV file  : %s\n"
            "  Waiting for ASSIGN_VISIT command on MQTT…",
            settings.stethoscope_device_id,
            self._wav_path,
        )
        self._running = True

        def _shutdown(signum: int, frame: object) -> None:
            logger.info("Shutdown signal received.")
            self._running = False

        signal.signal(signal.SIGINT, _shutdown)
        signal.signal(signal.SIGTERM, _shutdown)

        self._mqtt.connect()
        try:
            while self._running:
                time.sleep(0.1)
        finally:
            self._mqtt.disconnect()

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _handle_command(self, topic: str, payload: dict) -> None:
        """Dispatch incoming MQTT commands."""
        cmd_type = payload.get("type")

        if cmd_type == "ASSIGN_VISIT":
            visit_id = payload.get("visitId") or payload.get("visit_id")
            if not visit_id:
                logger.warning("ASSIGN_VISIT command missing visitId – ignoring.")
                return
            logger.info("Received ASSIGN_VISIT for visit %s", visit_id)
            self._current_visit_id = visit_id
            self._simulate_recording(visit_id)
        else:
            logger.warning("Unknown command type '%s' – ignoring.", cmd_type)

    def _simulate_recording(self, visit_id: str) -> None:
        """
        Core simulation flow:
          1. Publish VISIT_ASSIGNED (if triggered by MQTT command)
          2. Publish RECORDING_STARTED
          3. Wait (simulate auscultation)
          4. Publish RECORDING_STOPPED
          5. Run upload flow
        """
        device_id = settings.stethoscope_device_id

        # Publish VISIT_ASSIGNED if we have a current visit (set by command handler)
        if self._current_visit_id == visit_id:
            self._mqtt.publish_event(
                VisitAssignedEvent(device_id=device_id, visit_id=visit_id)
            )

        # RECORDING_STARTED
        self._mqtt.publish_event(
            RecordingStartedEvent(device_id=device_id, visit_id=visit_id)
        )
        logger.info("Recording started for visit %s (simulating for %.1fs)…",
                    visit_id, settings.recording_delay_seconds)

        # Simulate auscultation time
        time.sleep(settings.recording_delay_seconds)

        # RECORDING_STOPPED
        self._mqtt.publish_event(
            RecordingStoppedEvent(device_id=device_id, visit_id=visit_id)
        )
        logger.info("Recording stopped. Starting upload flow.")

        # Upload flow
        success = self._client.run_upload_flow(visit_id, self._wav_path)
        if success:
            logger.info("Simulation complete for visit %s.", visit_id)
        else:
            logger.error("Simulation failed for visit %s.", visit_id)

        # In listen mode, reset ready for the next visit
        self._current_visit_id = None


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="RespiCare electronic stethoscope device simulator.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--visit-id",
        metavar="UUID",
        help="Visit UUID to simulate (skips MQTT listen mode).",
    )
    parser.add_argument(
        "--wav",
        metavar="PATH",
        help="Path to WAV file to use as the simulated recording.",
    )
    parser.add_argument(
        "--delay",
        metavar="SECONDS",
        type=float,
        help="Override the simulated auscultation delay (default from config).",
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()

    # Resolve WAV path: CLI > config default
    wav_path: Optional[Path] = None
    if args.wav:
        wav_path = Path(args.wav)
    elif settings.default_wav_path:
        wav_path = settings.default_wav_path

    if wav_path is None:
        print(
            "Error: no WAV file specified. "
            "Use --wav /path/to/file.wav or set DEFAULT_WAV_PATH in .env",
            file=sys.stderr,
        )
        sys.exit(1)

    if args.delay is not None:
        # Override the config value for this run
        settings.recording_delay_seconds = args.delay

    sim = StethoscopeSimulator(wav_path=wav_path)

    if args.visit_id:
        sim.run_with_visit(args.visit_id)
    else:
        sim.run_listen_mode()


if __name__ == "__main__":
    main()
