"""Kafka producer wrapper: publishes AlertMessage to the alerts.raw topic."""

from confluent_kafka import Producer

from webhook.schemas import AlertMessage


class AlertProducer:
    def __init__(self, bootstrap_servers: str, topic: str = "alerts.raw") -> None:
        self._topic = topic
        self._producer = Producer({"bootstrap.servers": bootstrap_servers, "acks": "all"})

    def produce(self, message: AlertMessage) -> None:
        self._producer.produce(
            self._topic,
            key=message.fingerprint.encode("utf-8"),
            value=message.model_dump_json().encode("utf-8"),
        )
        self._producer.poll(0)
        self._producer.flush(timeout=10)

    def healthcheck(self) -> bool:
        try:
            self._producer.list_topics(timeout=5)
            return True
        except Exception:
            return False
