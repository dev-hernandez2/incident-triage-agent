FROM python:3.12-slim AS base
RUN pip install --no-cache-dir uv
WORKDIR /app
COPY pyproject.toml uv.lock ./
COPY db ./db
COPY llm ./llm
COPY obs ./obs
COPY services/webhook ./services/webhook
RUN uv sync --frozen --package triage-webhook --no-dev
EXPOSE 8000
CMD ["uv", "run", "--package", "triage-webhook", "uvicorn", "webhook.main:app", "--host", "0.0.0.0", "--port", "8000"]
