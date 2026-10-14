# Local cluster setup

`make up` brings up a local `kind` cluster running Google's Online Boutique
demo app plus a monitoring stack (Prometheus, Alertmanager, Grafana, Loki).
`make down` tears it down.

## Prerequisites

- **A container runtime.** This project is developed against
  [Podman](https://podman.io/) (not Docker). `kind` talks to Podman via
  `KIND_EXPERIMENTAL_PROVIDER=podman`, which the Makefile sets automatically.
  - Make sure a Podman machine is running with enough memory:
    ```sh
    podman machine set --memory 10240   # only needed once, or to resize
    podman machine start
    ```
  - Docker Desktop (or Docker Engine) also works if you prefer it — just
    unset `KIND_EXPERIMENTAL_PROVIDER` or override it to the empty string
    when running `make up`/`make down`.
- [`kind`](https://kind.sigs.k8s.io/) — `brew install kind`
- [`kubectl`](https://kubernetes.io/docs/tasks/tools/) — `brew install kubectl`
- [`helm`](https://helm.sh/) — `brew install helm`
- [`kustomize`](https://kustomize.io/) is not required separately;
  `kubectl apply -k` is used.

## Usage

```sh
make up     # idempotent: safe to re-run
make down   # delete the kind cluster
```

`make up` prints the Grafana/Prometheus/Boutique URLs and the
`kubectl port-forward` commands to reach them once it finishes. Example:

```sh
kubectl port-forward -n monitoring svc/kube-prometheus-stack-grafana 3000:80
# then open http://localhost:3000, login admin / admin
```

## What gets deployed

- **Namespace `boutique`**: Online Boutique (microservices-demo) v0.10.7,
  pinned manifest vendored under `deploy/boutique/base/`, with a Kustomize
  overlay (`deploy/boutique/overlay/`) that trims container resource
  requests/limits so the whole stack plus monitoring fits comfortably under
  ~8GB RAM. The built-in `loadgenerator` deployment is kept running.
- **Namespace `monitoring`**: `kube-prometheus-stack` (Prometheus,
  Alertmanager, Grafana), plus `loki` and `promtail`, installed via Helm
  with pinned chart versions and values files under `deploy/monitoring/`.
  No persistent storage is used — this cluster is meant to be ephemeral.
- **`PrometheusRule`** (`deploy/monitoring/boutique-alerts.yaml`): alerts for
  pod crash looping, OOMKilled, high error rate, high p95 latency, CPU
  throttling, and pod not ready, scoped to the `boutique` namespace. Online
  Boutique exposes no app-level HTTP/gRPC metrics, so the error-rate and
  latency alerts are approximated from container-level signals (restart
  rate, CPU throttling) rather than real request metrics — good enough to
  exercise the triage agent, not a substitute for real APM.

## Troubleshooting

- **`podman machine` isn't running / kind create cluster hangs or fails to
  connect**: run `podman machine start` and confirm `podman ps` succeeds
  before retrying `make up`.
- **OOM / pods stuck Pending with "Insufficient memory"**: your Podman
  machine likely doesn't have enough RAM allocated. Resize it:
  ```sh
  podman machine stop
  podman machine set --memory 10240
  podman machine start
  ```
- **`helm upgrade --install` times out waiting for pods**: check pod events
  with `kubectl describe pod -n monitoring <pod>` — on a cold run, image
  pulls for the monitoring stack can take a few minutes depending on your
  network.
- **`make up` run a second time does nothing destructive**: it detects the
  existing `triage` kind cluster and skips cluster creation, and all
  `kubectl apply` / `helm upgrade --install` calls are themselves idempotent.
- **Starting over cleanly**: `make down && make up`.
- **Alert rules show "boutique.rules group not yet synced" right after
  `make up`**: the Prometheus Operator reconciles new `PrometheusRule`
  objects on its own loop; it can take up to ~1-2 minutes after `make up`
  finishes for `boutique-alerts` to appear in Prometheus's `/api/v1/rules`.
  This is normal and not a failure.
- **Loki pod crashes with `mkdir /var/loki: read-only file system`**: this
  chart (with `singleBinary.persistence.enabled: false`) does not fall back
  to an `emptyDir` for its data directory, and the container runs with
  `readOnlyRootFilesystem: true`. `deploy/monitoring/loki-values.yaml`
  works around this with an explicit `extraVolumes`/`extraVolumeMounts`
  entry mounting an `emptyDir` at `/var/loki`. If you see this error after
  editing the values file, check that mount is still present.
- **Boutique services get OOMKilled under real load despite having headroom
  on paper**: JVM (`adservice`) and .NET (`cartservice`) services have a
  materially higher baseline memory footprint than the Go/Python services
  once the loadgenerator and Prometheus scraping are running. The overlay's
  memory limits were sized from measured `container_memory_working_set_bytes`
  under load, not from upstream defaults — if you trim them further, re-test
  under load (`make up`, wait a few minutes, check
  `kubectl get pods -n boutique` for `OOMKilled`/restarts) rather than
  assuming idle-state numbers hold.
- **`BoutiqueCPUThrottlingHigh` fires even though the app looks healthy**:
  CPU *limits* cause CFS quota throttling on short request bursts even when
  average usage is a few millicores — a classic "set a cpu limit, get
  throttled" trap. The overlay intentionally sets only `requests.cpu`, no
  `limits.cpu`, for the boutique services. If you add CPU limits back,
  expect this alert to become noisy.
