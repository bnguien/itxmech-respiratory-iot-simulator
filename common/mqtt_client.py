"""
Shared MQTT client wrapper built on top of paho-mqtt.

Handles:
- Connection with optional username/password
- Configurable Last Will message
- QoS-1 publish helpers
- Retained message publish for status
- Clean reconnect/disconnect
"""

from __future__ import annotations

import logging
import time
from typing import Callable, Optional

import paho.mqtt.client as mqtt

from common.config import settings
from common.models import (
    BaseMessage,
    DeviceStatusMessage,
    mqtt_topic,
    new_message_id,
    utc_now,
)

logger = logging.getLogger(__name__)


class MqttClient:
    """
    Thin wrapper around paho-mqtt for RespiCare device simulators.

    Usage::

        client = MqttClient(device_id="RESPICARE-STETH-001")
        client.connect()
        client.publish_event(SomeEvent(...))
        client.disconnect()
    """

    def __init__(
        self,
        device_id: str,
        *,
        host: Optional[str] = None,
        port: Optional[int] = None,
        username: Optional[str] = None,
        password: Optional[str] = None,
        on_command: Optional[Callable[[str, dict], None]] = None,
    ) -> None:
        self.device_id = device_id
        self._host = host or settings.mqtt_host
        self._port = port or settings.mqtt_port
        self._username = username or settings.mqtt_username
        self._password = password or settings.mqtt_password
        self._on_command = on_command

        self._client = mqtt.Client(
            client_id=f"respicare-sim-{device_id}",
            clean_session=True,
        )

        # ----------------------------------------------------------------
        # Last Will – published by broker if the client disconnects
        #             unexpectedly (i.e. without calling disconnect()).
        # ----------------------------------------------------------------
        offline_msg = DeviceStatusMessage(
            type="DEVICE_OFFLINE",
            device_id=device_id,
            message_id=new_message_id(),
            timestamp=utc_now(),
        )
        self._client.will_set(
            topic=mqtt_topic(device_id, "status"),
            payload=offline_msg.to_json(),
            qos=1,
            retain=True,
        )

        if self._username:
            self._client.username_pw_set(self._username, self._password)

        self._client.on_connect = self._on_connect
        self._client.on_disconnect = self._on_disconnect
        self._client.on_message = self._on_message

    # ------------------------------------------------------------------
    # Connection lifecycle
    # ------------------------------------------------------------------

    def connect(self, timeout: float = 10.0) -> None:
        """Connect to the MQTT broker and block until connected (or timeout)."""
        logger.info(
            "Connecting to MQTT broker %s:%s as device %s",
            self._host,
            self._port,
            self.device_id,
        )
        self._client.connect(self._host, self._port, keepalive=60)
        self._client.loop_start()

        # Wait until connected or timeout
        deadline = time.time() + timeout
        while not self._client.is_connected() and time.time() < deadline:
            time.sleep(0.05)

        if not self._client.is_connected():
            raise ConnectionError(
                f"Could not connect to MQTT broker at {self._host}:{self._port} "
                f"within {timeout:.1f}s. Is Mosquitto running?"
            )

        # Subscribe to command topic
        command_topic = mqtt_topic(self.device_id, "command")
        self._client.subscribe(command_topic, qos=1)
        logger.info("Subscribed to %s", command_topic)

        # Announce device online (retained)
        self._publish_status_online()

    def disconnect(self) -> None:
        """Clean shutdown: publish DEVICE_OFFLINE retained, then disconnect."""
        self._publish_status_offline()
        self._client.loop_stop()
        self._client.disconnect()
        logger.info("MQTT client disconnected cleanly.")

    # ------------------------------------------------------------------
    # Publish helpers
    # ------------------------------------------------------------------

    def publish_event(self, message: BaseMessage, qos: int = 1) -> None:
        """Publish an event message on the device's event topic."""
        topic = mqtt_topic(self.device_id, "event")
        payload = message.to_json()
        result = self._client.publish(topic, payload, qos=qos)
        result.wait_for_publish(timeout=5.0)
        logger.debug("Published event %s to %s", message.type, topic)

    def publish_status(self, message: BaseMessage, retained: bool = True) -> None:
        """Publish a status message, retained by default."""
        topic = mqtt_topic(self.device_id, "status")
        payload = message.to_json()
        self._client.publish(topic, payload, qos=1, retain=retained)
        logger.debug("Published status %s to %s (retain=%s)", message.type, topic, retained)

    # ------------------------------------------------------------------
    # Internal callbacks
    # ------------------------------------------------------------------

    def _on_connect(
        self,
        client: mqtt.Client,
        userdata: object,
        flags: dict,
        rc: int,
    ) -> None:
        if rc == 0:
            logger.info("MQTT connected (rc=0)")
        else:
            logger.error("MQTT connection failed with rc=%d", rc)

    def _on_disconnect(
        self,
        client: mqtt.Client,
        userdata: object,
        rc: int,
    ) -> None:
        if rc == 0:
            logger.debug("MQTT disconnected cleanly.")
        else:
            logger.warning("MQTT unexpected disconnect (rc=%d). Will attempt reconnect.", rc)

    def _on_message(
        self,
        client: mqtt.Client,
        userdata: object,
        msg: mqtt.MQTTMessage,
    ) -> None:
        try:
            import json

            payload = json.loads(msg.payload.decode("utf-8"))
            logger.info(
                "Received command on %s: type=%s",
                msg.topic,
                payload.get("type", "unknown"),
            )
            if self._on_command:
                self._on_command(msg.topic, payload)
        except Exception as exc:
            logger.error("Failed to parse incoming message on %s: %s", msg.topic, exc)

    # ------------------------------------------------------------------
    # Status helpers
    # ------------------------------------------------------------------

    def _publish_status_online(self) -> None:
        msg = DeviceStatusMessage(
            type="DEVICE_ONLINE",
            device_id=self.device_id,
        )
        self.publish_status(msg)
        logger.info("Device %s is ONLINE (retained status published)", self.device_id)

    def _publish_status_offline(self) -> None:
        msg = DeviceStatusMessage(
            type="DEVICE_OFFLINE",
            device_id=self.device_id,
        )
        self.publish_status(msg)
        logger.info("Device %s is OFFLINE (retained status published)", self.device_id)
