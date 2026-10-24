#!/usr/bin/env bash
set -euo pipefail

CLUSTER_NAME="triage"
DEMO_SERVICE="${DEMO_SERVICE:-cartservice}"
LOG_DIR="/tmp/triage-demo-logs"
PIDS=()

cleanup() {
  echo ""
  echo "Cleaning up demo processes..."
  for pid in "${PIDS[@]:-}"; do
    kill "$pid" 2>/dev/null || true
  done
  for pid in "${PIDS[@]:-}"; do
    for _ in $(seq 1 5); do
      kill -0 "$pid" 2>/dev/null || break
      sleep 1
    done
    kill -9 "$pid" 2>/dev/null || true
  done
  wait 2>/dev/null || true
}
trap cleanup EXIT INT TERM

if ! kind get clusters 2>/dev/null | grep -qx "$CLUSTER_NAME"; then
  echo "No '$CLUSTER_NAME' kind cluster found. Run 'make up' first." >&2
  exit 1
fi
kubectl config use-context "kind-$CLUSTER_NAME" >/dev/null

mkdir -p "$LOG_DIR"

echo "Starting port-forwards..."
kubectl port-forward -n triage svc/kafka 9092:9092 >"$LOG_DIR/pf-kafka.log" 2>&1 &
PIDS+=($!)
kubectl port-forward -n triage svc/postgres-postgresql 5432:5432 >"$LOG_DIR/pf-postgres.log" 2>&1 &
PIDS+=($!)
kubectl port-forward -n monitoring svc/kube-prometheus-stack-prometheus 9090:9090 >"$LOG_DIR/pf-prometheus.log" 2>&1 &
PIDS+=($!)
kubectl port-forward -n monitoring svc/loki 3100:3100 >"$LOG_DIR/pf-loki.log" 2>&1 &
PIDS+=($!)

for port in 9092 5432 9090 3100; do
  for _ in $(seq 1 30); do
    nc -z localhost "$port" && break
    sleep 1
  done
done

echo "Starting services..."
uv run --package triage-webhook uvicorn webhook.main:app --host 0.0.0.0 --port 8000 >"$LOG_DIR/webhook.log" 2>&1 &
PIDS+=($!)
uv run --package triage-agent-svc python -m agent.main >"$LOG_DIR/agent.log" 2>&1 &
PIDS+=($!)
uv run --package triage-bot python -m bot.main >"$LOG_DIR/bot.log" 2>&1 &
PIDS+=($!)
uv run --package triage-executor python -m executor.main >"$LOG_DIR/executor.log" 2>&1 &
PIDS+=($!)
uv run --package triage-dashboard uvicorn dashboard.main:app --host 0.0.0.0 --port 8001 >"$LOG_DIR/dashboard.log" 2>&1 &
PIDS+=($!)

for port in 8000 8001; do
  for _ in $(seq 1 30); do
    nc -z localhost "$port" && break
    sleep 1
  done
done
echo "Services up. Logs in $LOG_DIR/"

echo "Injecting bad_deploy against $DEMO_SERVICE..."
uv run --all-packages chaos inject bad_deploy --service "$DEMO_SERVICE"

echo ""
echo "=================================================================="
echo " Watch the incident investigation:"
echo "   Discord channel: ${DISCORD_CHANNEL_ID:-<set DISCORD_CHANNEL_ID in .env>}"
echo "   Dashboard:       http://localhost:8001"
echo " The agent typically posts a root-cause summary within ~30-60s."
echo "=================================================================="
echo ""
echo "Waiting 5 minutes for the investigation and approval flow, then reverting..."
sleep 300

echo "Reverting bad_deploy..."
uv run --all-packages chaos revert
echo "Demo complete."
