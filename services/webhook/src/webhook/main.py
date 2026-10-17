"""FastAPI receiver: Alertmanager webhook -> Kafka topic `alerts.raw`."""

import os
from functools import lru_cache

from fastapi import Depends, FastAPI, HTTPException

from webhook.kafka_producer import AlertProducer
from webhook.logging_config import configure_logging
from webhook.schemas import AlertmanagerWebhookPayload, to_alert_message

app = FastAPI(title="triage-agent webhook")
logger = configure_logging()


@lru_cache
def get_producer() -> AlertProducer:
    bootstrap_servers = os.environ.get("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")
    return AlertProducer(bootstrap_servers=bootstrap_servers)


@app.post("/alerts")
async def receive_alert(
    payload: AlertmanagerWebhookPayload,
    producer: AlertProducer = Depends(get_producer),
) -> dict[str, int]:
    for alert in payload.alerts:
        message = to_alert_message(alert)
        try:
            producer.produce(message)
        except Exception as exc:
            raise HTTPException(status_code=502, detail="failed to publish to kafka") from exc
        logger.info(
            "published alert",
            extra={
                "fingerprint": message.fingerprint,
                "alertname": message.alertname,
                "status": message.status,
            },
        )
    return {"accepted": len(payload.alerts)}


@app.get("/healthz")
async def healthz(producer: AlertProducer = Depends(get_producer)) -> dict[str, str]:
    if not producer.healthcheck():
        raise HTTPException(status_code=503, detail="kafka unreachable")
    return {"status": "ok"}
