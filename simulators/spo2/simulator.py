"""
SpO2 wearable device simulator — scaffold.

This is a minimal scaffold for the SpO2 device simulator.
Real-time SpO2 readings are published as MQTT events at a configurable interval.

Usage:
    python -m simulators.spo2.simulator \\
        --visit-id <UUID> \\
        --spo2 97

The SpO2 AI analysis is NOT implemented here.
"""

from __future__ import annotations

import argparse
import logging
import signal
import time
from typing import Optional

from common.config import settings
from common.models import Spo2ReadingEvent
from common.mqtt_client import MqttClient

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
logger = logging.getLogger(__name__)

_DEFAULT_SPO2 = 97
_DEFAULT_INTERVAL_SECONDS = 5.0
_DEFAULT_DURATION_SECONDS = 60.0  # total time to publish readings (0 = run until Ctrl-C)


class Spo2Simulator:
    """
    Scaffold for a RespiCare SpO2 wearable simulator.

    Publishes synthetic SpO2 readings at a fixed interval.
    Real sensor integration and AI analysis are out of scope for this simulator.
    """

    def __init__(
        self,
        visit_id: str,
        spo2: int = _DEFAULT_SPO2,
        interval: float = _DEFAULT_INTERVAL_SECONDS,
    ) -> None:
        self._visit_id = visit_id
        self._spo2 = spo2
        self._interval = interval
        self._running = False

        self._mqtt = MqttClient(device_id=settings.spo2_device_id)

    def run(self, duration: float = _DEFAULT_DURATION_SECONDS) -> None:
        """
        Connect to MQTT and publish SpO2 readings.

        Args:
            duration: Total seconds to run. 0 means run until Ctrl-C.
        """
        logger.info(
            "=== SpO2 Simulator (scaffold) ===\n"
            "  Device ID : %s\n"
            "  Visit ID  : %s\n"
            "  SpO2      : %d%%\n"
            "  Interval  : %.1fs\n"
            "  Duration  : %s",
            settings.spo2_device_id,
            self._visit_id,
            self._spo2,
            self._interval,
            f"{duration:.0f}s" if duration > 0 else "until Ctrl-C",
        )

        self._running = True

        def _shutdown(signum: int, frame: object) -> None:
            logger.info("SpO2 simulator shutting down.")
            self._running = False

        signal.signal(signal.SIGINT, _shutdown)
        signal.signal(signal.SIGTERM, _shutdown)

        self._mqtt.connect()
        start = time.time()
        try:
            while self._running:
                self._publish_reading()
                time.sleep(self._interval)
                if duration > 0 and (time.time() - start) >= duration:
                    break
        finally:
            self._mqtt.disconnect()

    def _publish_reading(self) -> None:
        event = Spo2ReadingEvent(
            device_id=settings.spo2_device_id,
            visit_id=self._visit_id,
            spo2=self._spo2,
        )
        # SpO2 readings use QoS 0 (best-effort) for low latency real-time streaming
        self._mqtt.publish_event(event, qos=0)
        logger.info("Published SpO2 reading: %d%% for visit %s", self._spo2, self._visit_id)


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="RespiCare SpO2 wearable simulator (scaffold).",
    )
    parser.add_argument(
        "--visit-id",
        metavar="UUID",
        required=True,
        help="Visit UUID to associate SpO2 readings with.",
    )
    parser.add_argument(
        "--spo2",
        metavar="PCT",
        type=int,
        default=_DEFAULT_SPO2,
        help=f"Simulated SpO2 percentage (0-100). Default: {_DEFAULT_SPO2}",
    )
    parser.add_argument(
        "--interval",
        metavar="SECONDS",
        type=float,
        default=_DEFAULT_INTERVAL_SECONDS,
        help=f"Interval between readings in seconds. Default: {_DEFAULT_INTERVAL_SECONDS}",
    )
    parser.add_argument(
        "--duration",
        metavar="SECONDS",
        type=float,
        default=0.0,
        help="Total duration to run (0 = run until Ctrl-C). Default: 0",
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    sim = Spo2Simulator(
        visit_id=args.visit_id,
        spo2=args.spo2,
        interval=args.interval,
    )
    sim.run(duration=args.duration)


if __name__ == "__main__":
    main()
