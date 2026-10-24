FROM python:3.12-slim AS base
RUN pip install --no-cache-dir uv
WORKDIR /app
COPY pyproject.toml uv.lock ./
COPY db ./db
COPY llm ./llm
COPY obs ./obs
COPY services/agent ./services/agent
RUN uv sync --frozen --package triage-agent-svc --no-dev
EXPOSE 9100
CMD ["uv", "run", "--package", "triage-agent-svc", "python", "-m", "agent.main"]
