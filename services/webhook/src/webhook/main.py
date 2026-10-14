"""FastAPI receiver: Alertmanager webhook -> Kafka topic `alerts.raw`."""

from fastapi import FastAPI

app = FastAPI(title="triage-agent webhook")


@app.post("/alerts")
async def receive_alert() -> dict[str, str]:
    # TODO: validate Alertmanager payload and publish to Kafka `alerts.raw`
    raise NotImplementedError
