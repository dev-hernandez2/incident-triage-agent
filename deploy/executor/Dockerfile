FROM python:3.12-slim AS base
RUN pip install --no-cache-dir uv
WORKDIR /app
COPY pyproject.toml uv.lock ./
COPY db ./db
COPY llm ./llm
COPY obs ./obs
COPY services/executor ./services/executor
RUN uv sync --frozen --package triage-executor --no-dev
CMD ["uv", "run", "--package", "triage-executor", "python", "-m", "executor.main"]
