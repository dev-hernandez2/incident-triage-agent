# Argo CD GitOps Migration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move Online Boutique from direct `kubectl apply -k` deploys to
Argo CD syncing from an in-cluster Gitea repo, and rewrite `chaos`'s
`bad_deploy` scenario to inject/revert its fault via a Git commit instead
of a direct Kubernetes API patch.

**Architecture:** `make up` gains two new Helm releases (Gitea, Argo CD)
and pushes `deploy/boutique/` into a new Gitea-hosted repo
(`boutique-deploy`) once; an Argo CD `Application` syncs that repo into
the `boutique` namespace, replacing the old `kubectl apply -k` step.
`chaos` gains a small git-plumbing module that clones `boutique-deploy`
into a local working copy, and `bad_deploy.py` is rewritten to edit a
kustomize patch there, commit, push, and poll Argo CD's sync status
instead of patching the live Deployment directly.

**Tech Stack:** Python 3.12, GitPython (new dependency for `chaos`),
kustomize (already in use via `kubectl apply -k`), Argo CD REST API
(via `httpx`, already a workspace dependency per `llm/`), Helm, kind.

**Spec:** [`docs/superpowers/specs/2026-10-21-argocd-tools-prompt-v2-design.md`](../specs/2026-10-21-argocd-tools-prompt-v2-design.md)
(section 1)

## Global Constraints

- Gitea and Argo CD stay in-cluster only — no push to any real external
  remote (GitHub, etc.).
- Only the `deploy/boutique/` subtree is mirrored into Gitea's
  `boutique-deploy` repo, not the whole incident-triage-agent repo.
- `chaos`'s own tests must stay offline — no real Gitea/Argo CD
  dependency in `chaos/tests/`, only in the real `make up` cluster.
- `bad_deploy.inject()`/`revert()` must preserve their existing contract:
  the fault (or its reversal) is live in the cluster by the time the
  call returns — callers must not have to separately wait for sync.
- Python 3.12, type hints everywhere, `mypy --strict` must pass,
  `ruff check` must pass.
- `uv run --all-packages` (not bare `uv run`) for any command touching
  more than the `chaos` package alone.

## Review Focus

- **Argo CD not yet synced when `bad_deploy` returns**: a test must
  confirm `inject()`/`revert()` block until the polled sync status
  matches the pushed commit SHA, not just until the push succeeds —
  otherwise the eval harness or a human could observe a stale cluster
  state right after the call returns.
- **Gitea push races with a prior unfinished chaos run**: `chaos status`
  already refuses a second `inject` while one is active (existing CLI
  behavior) — a test must confirm the new git-based `inject`/`revert`
  still respects that single-active-scenario invariant and doesn't leave
  the local clone in a half-committed state if interrupted.
- **First-run clone when `chaos/.state/boutique-deploy/` doesn't exist
  yet**: a test must cover the clone-on-first-use path (not just the
  already-cloned path), since this is the only place new cold-start
  logic lives.
- **Revert of a revert / double-revert**: a test must confirm calling
  `revert()` twice (or reverting without a prior `inject()` snapshot)
  fails clearly rather than pushing a bogus commit — matches today's
  implicit assumption that `revert()` is only ever called with a real
  snapshot from `inject()`.
- **Sync status poll never reaches `Synced`**: a test must cover a
  timeout path (Argo CD stuck `OutOfSync`/`Progressing`) so `inject()`
  raises a clear error instead of hanging forever or silently returning
  with the fault not actually live.

---

## File Structure

- `chaos/src/chaos/git_repo.py` (new) — git plumbing: clone-if-absent,
  commit, push, read current HEAD SHA.
- `chaos/src/chaos/argocd_sync.py` (new) — Argo CD REST client limited to
  what `bad_deploy` needs: read an `Application`'s sync status and
  revision; poll until a target revision is `Synced`.
- `chaos/src/chaos/scenarios/bad_deploy.py` (modify) — rewrite
  `inject()`/`revert()` to use `git_repo.py` + `argocd_sync.py` instead of
  `k8s.patch_containers`.
- `deploy/boutique/overlay/kustomization.yaml` (modify) — add a
  `does-not-exist`-tag image patch block for `bad_deploy` to toggle, kept
  separate from the existing resource-limit patches.
- `deploy/k8s/argocd-boutique-app.yaml` (new) — Argo CD `Application`
  manifest pointing at Gitea's `boutique-deploy` repo.
- `deploy/k8s/gitea-values.yaml` (new) — Helm values for the in-cluster
  Gitea release (minimal: single-node, no persistence beyond the kind
  node's default, admin token pre-seeded for scripted repo creation).
- `Makefile` (modify) — add Gitea + Argo CD Helm installs, the
  one-time `boutique-deploy` repo push, and the Argo CD `Application`
  apply; remove the old `kubectl apply -k deploy/boutique/overlay/` step
  for Online Boutique.
- `chaos/tests/fake_git_remote.py` (new) — a local bare-repo fixture
  standing in for Gitea in tests.
- `chaos/tests/fake_argocd.py` (new) — a fake Argo CD sync-status server
  (or stubbed HTTP client) standing in for the real Argo CD API in tests.
- `chaos/tests/test_bad_deploy.py` (modify) — rewrite to use the new
  fakes instead of `FakeK8sClient`.
- `chaos/pyproject.toml` (modify) — add `GitPython` and `httpx`
  dependencies.

## Task 1: Git plumbing module

**Files:**
- Create: `chaos/src/chaos/git_repo.py`
- Test: `chaos/tests/test_git_repo.py`
- Modify: `chaos/pyproject.toml` (add `GitPython>=3.1` dependency)

**Interfaces:**
- Consumes: nothing from other tasks.
- Produces: `chaos.git_repo.BoutiqueDeployRepo` class with:
  - `__init__(self, remote_url: str, local_path: Path) -> None`
  - `ensure_cloned(self) -> None` — clones `remote_url` into `local_path`
    if it doesn't exist yet; no-ops if it already does (and pulls latest).
  - `write_file(self, relative_path: str, content: str) -> None` — writes
    `content` to `local_path / relative_path`.
  - `commit_and_push(self, message: str) -> str` — stages all changes,
    commits with `message`, pushes to the remote's default branch,
    returns the new commit SHA.
  - `head_sha(self) -> str` — returns current local HEAD SHA without
    pushing (used by revert's "nothing to revert" check).

- [ ] **Step 1: Add GitPython dependency**

Edit `chaos/pyproject.toml`, add to `dependencies`:
```toml
    "GitPython>=3.1",
```

Run: `cd "chaos" && uv sync --all-packages` (run from repo root:
`uv sync --all-packages`)
Expected: resolves and installs GitPython with no errors.

- [ ] **Step 2: Write the failing test for ensure_cloned on a fresh path**

```python
# chaos/tests/test_git_repo.py
from pathlib import Path

import git
import pytest

from chaos.git_repo import BoutiqueDeployRepo


@pytest.fixture
def bare_remote(tmp_path: Path) -> Path:
    remote_path = tmp_path / "remote.git"
    git.Repo.init(remote_path, bare=True)
    # Seed the bare remote with one commit so clone has something to check out.
    seed_path = tmp_path / "seed"
    seed_repo = git.Repo.init(seed_path)
    (seed_path / "overlay.yaml").write_text("placeholder: true\n")
    seed_repo.index.add(["overlay.yaml"])
    seed_repo.index.commit("seed")
    seed_repo.create_remote("origin", str(remote_path))
    default_branch = seed_repo.active_branch.name
    seed_repo.remote("origin").push(default_branch)
    return remote_path


def test_ensure_cloned_clones_fresh_path(bare_remote: Path, tmp_path: Path) -> None:
    local_path = tmp_path / "working-copy"
    repo = BoutiqueDeployRepo(remote_url=str(bare_remote), local_path=local_path)

    repo.ensure_cloned()

    assert (local_path / "overlay.yaml").exists()
    assert (local_path / ".git").is_dir()
```

- [ ] **Step 3: Run test to verify it fails**

Run: `uv run --all-packages pytest chaos/tests/test_git_repo.py::test_ensure_cloned_clones_fresh_path -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'chaos.git_repo'`

- [ ] **Step 4: Implement BoutiqueDeployRepo.ensure_cloned**

```python
# chaos/src/chaos/git_repo.py
from pathlib import Path

import git


class BoutiqueDeployRepo:
    def __init__(self, remote_url: str, local_path: Path) -> None:
        self.remote_url = remote_url
        self.local_path = local_path
        self._repo: git.Repo | None = None

    def ensure_cloned(self) -> None:
        if (self.local_path / ".git").is_dir():
            self._repo = git.Repo(self.local_path)
            self._repo.remote("origin").pull()
            return
        self._repo = git.Repo.clone_from(self.remote_url, self.local_path)

    @property
    def repo(self) -> git.Repo:
        if self._repo is None:
            raise RuntimeError("call ensure_cloned() before using the repo")
        return self._repo
```

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run --all-packages pytest chaos/tests/test_git_repo.py::test_ensure_cloned_clones_fresh_path -v`
Expected: PASS

- [ ] **Step 6: Write the failing test for ensure_cloned on an already-cloned path (pulls instead of re-cloning)**

```python
def test_ensure_cloned_pulls_when_already_cloned(bare_remote: Path, tmp_path: Path) -> None:
    local_path = tmp_path / "working-copy"
    repo = BoutiqueDeployRepo(remote_url=str(bare_remote), local_path=local_path)
    repo.ensure_cloned()

    # Someone else pushes a new commit to the remote.
    other_clone_path = tmp_path / "other-clone"
    other_repo = git.Repo.clone_from(str(bare_remote), other_clone_path)
    (other_clone_path / "overlay.yaml").write_text("placeholder: false\n")
    other_repo.index.add(["overlay.yaml"])
    other_repo.index.commit("update")
    other_repo.remote("origin").push()

    repo2 = BoutiqueDeployRepo(remote_url=str(bare_remote), local_path=local_path)
    repo2.ensure_cloned()

    assert (local_path / "overlay.yaml").read_text() == "placeholder: false\n"
```

- [ ] **Step 7: Run test to verify it passes**

Run: `uv run --all-packages pytest chaos/tests/test_git_repo.py -v`
Expected: Both tests PASS (the pull branch in Step 4's implementation
already handles this.)

- [ ] **Step 8: Write the failing test for write_file + commit_and_push + head_sha**

```python
def test_write_commit_push_and_head_sha(bare_remote: Path, tmp_path: Path) -> None:
    local_path = tmp_path / "working-copy"
    repo = BoutiqueDeployRepo(remote_url=str(bare_remote), local_path=local_path)
    repo.ensure_cloned()

    repo.write_file("overlay.yaml", "placeholder: changed\n")
    sha = repo.commit_and_push("test: change placeholder")

    assert sha == repo.head_sha()
    assert len(sha) == 40

    # A fresh clone from the remote sees the pushed change.
    verify_path = tmp_path / "verify-clone"
    git.Repo.clone_from(str(bare_remote), verify_path)
    assert (verify_path / "overlay.yaml").read_text() == "placeholder: changed\n"
```

- [ ] **Step 9: Run test to verify it fails**

Run: `uv run --all-packages pytest chaos/tests/test_git_repo.py::test_write_commit_push_and_head_sha -v`
Expected: FAIL with `AttributeError: 'BoutiqueDeployRepo' object has no attribute 'write_file'`

- [ ] **Step 10: Implement write_file, commit_and_push, head_sha**

```python
    def write_file(self, relative_path: str, content: str) -> None:
        target = self.local_path / relative_path
        target.write_text(content)

    def commit_and_push(self, message: str) -> str:
        self.repo.git.add(A=True)
        self.repo.index.commit(message)
        self.repo.remote("origin").push()
        return self.repo.head.commit.hexsha

    def head_sha(self) -> str:
        return self.repo.head.commit.hexsha
```

- [ ] **Step 11: Run all git_repo tests to verify they pass**

Run: `uv run --all-packages pytest chaos/tests/test_git_repo.py -v`
Expected: All 3 tests PASS

- [ ] **Step 12: Lint and typecheck**

Run: `uv run --all-packages ruff check chaos/src/chaos/git_repo.py chaos/tests/test_git_repo.py && uv run --all-packages mypy chaos/src/chaos/git_repo.py chaos/tests/test_git_repo.py`
Expected: no errors. If GitPython lacks type stubs, add `types-GitPython`
dev dependency (mypy will tell you if this is needed).

- [ ] **Step 13: Commit**

```bash
git add chaos/src/chaos/git_repo.py chaos/tests/test_git_repo.py chaos/pyproject.toml uv.lock
git commit -m "feat(chaos): add git plumbing module for GitOps-based fault injection"
```

## Task 2: Argo CD sync-status client

**Files:**
- Create: `chaos/src/chaos/argocd_sync.py`
- Test: `chaos/tests/test_argocd_sync.py`
- Create: `chaos/tests/fake_argocd.py`
- Modify: `chaos/pyproject.toml` (add `httpx>=0.27` dependency — check
  `llm/pyproject.toml` for the exact version already pinned there and
  match it)

**Interfaces:**
- Consumes: nothing from Task 1.
- Produces: `chaos.argocd_sync.ArgoCdClient` class with:
  - `__init__(self, base_url: str, app_name: str, token: str, *, http_client: httpx.Client | None = None) -> None`
  - `current_sync_revision(self) -> str` — returns the commit SHA Argo CD
    currently reports as synced for `app_name`.
  - `wait_for_sync(self, target_revision: str, *, timeout_s: float = 60, poll_interval_s: float = 2) -> None`
    — polls until `current_sync_revision() == target_revision` and sync
    status is `Synced`; raises `ArgoCdSyncTimeoutError` (new exception, same
    module) on timeout.

- [ ] **Step 1: Check the httpx version already pinned in llm/pyproject.toml**

Run: `grep httpx "llm/pyproject.toml"`
Use that exact version constraint in `chaos/pyproject.toml` for consistency.

- [ ] **Step 2: Add httpx dependency**

Edit `chaos/pyproject.toml`, add to `dependencies` (using the version
found in Step 1, e.g. if llm pins `httpx>=0.27`):
```toml
    "httpx>=0.27",
```

Run: `uv sync --all-packages`
Expected: resolves with no errors (httpx is likely already in the lockfile
from `llm/`).

- [ ] **Step 3: Write the fake Argo CD server fixture**

```python
# chaos/tests/fake_argocd.py
from typing import Any

import httpx


class FakeArgoCdTransport(httpx.BaseTransport):
    """Stands in for the real Argo CD REST API in tests."""

    def __init__(self) -> None:
        self.synced_revision = "0" * 40
        self.sync_status = "Synced"
        # Call set_synced_revision from a test to simulate Argo CD catching
        # up to a newly pushed commit mid-poll.
        self._poll_count = 0
        self.synced_after_polls: int | None = None
        self.pending_revision: str | None = None

    def set_synced_after(self, revision: str, polls: int) -> None:
        """Simulate Argo CD syncing `revision` after `polls` status checks."""
        self.pending_revision = revision
        self.synced_after_polls = polls
        self._poll_count = 0

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/sync-status")
        if self.synced_after_polls is not None:
            self._poll_count += 1
            if self._poll_count >= self.synced_after_polls:
                self.synced_revision = self.pending_revision or self.synced_revision
                self.sync_status = "Synced"
            else:
                self.sync_status = "Progressing"
        body: dict[str, Any] = {
            "revision": self.synced_revision,
            "status": self.sync_status,
        }
        return httpx.Response(200, json=body)
```

- [ ] **Step 4: Write the failing test for current_sync_revision**

```python
# chaos/tests/test_argocd_sync.py
import httpx

from chaos.argocd_sync import ArgoCdClient
from fake_argocd import FakeArgoCdTransport


def _client(transport: FakeArgoCdTransport) -> ArgoCdClient:
    http_client = httpx.Client(transport=transport, base_url="http://argocd.local")
    return ArgoCdClient(
        base_url="http://argocd.local",
        app_name="boutique",
        token="fake-token",
        http_client=http_client,
    )


def test_current_sync_revision_reads_from_api() -> None:
    transport = FakeArgoCdTransport()
    transport.synced_revision = "a" * 40
    client = _client(transport)

    assert client.current_sync_revision() == "a" * 40
```

- [ ] **Step 5: Run test to verify it fails**

Run: `uv run --all-packages pytest chaos/tests/test_argocd_sync.py::test_current_sync_revision_reads_from_api -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'chaos.argocd_sync'`

- [ ] **Step 6: Implement ArgoCdClient.current_sync_revision**

```python
# chaos/src/chaos/argocd_sync.py
import time

import httpx


class ArgoCdSyncTimeoutError(Exception):
    pass


class ArgoCdClient:
    def __init__(
        self,
        base_url: str,
        app_name: str,
        token: str,
        *,
        http_client: httpx.Client | None = None,
    ) -> None:
        self.app_name = app_name
        self._http = http_client or httpx.Client(
            base_url=base_url,
            headers={"Authorization": f"Bearer {token}"},
        )

    def _fetch_status(self) -> dict[str, str]:
        response = self._http.get(f"/api/v1/applications/{self.app_name}/sync-status")
        response.raise_for_status()
        data: dict[str, str] = response.json()
        return data

    def current_sync_revision(self) -> str:
        return self._fetch_status()["revision"]
```

- [ ] **Step 7: Run test to verify it passes**

Run: `uv run --all-packages pytest chaos/tests/test_argocd_sync.py::test_current_sync_revision_reads_from_api -v`
Expected: PASS

- [ ] **Step 8: Write the failing test for wait_for_sync succeeding after a few polls**

```python
def test_wait_for_sync_succeeds_after_polling(monkeypatch: "pytest.MonkeyPatch") -> None:
    monkeypatch.setattr("time.sleep", lambda _: None)
    transport = FakeArgoCdTransport()
    transport.set_synced_after("b" * 40, polls=3)
    client = _client(transport)

    client.wait_for_sync(target_revision="b" * 40, timeout_s=10, poll_interval_s=0)

    assert client.current_sync_revision() == "b" * 40
```

Add `import pytest` at the top of the test file if not already present
(needed for the `monkeypatch` type annotation).

- [ ] **Step 9: Run test to verify it fails**

Run: `uv run --all-packages pytest chaos/tests/test_argocd_sync.py::test_wait_for_sync_succeeds_after_polling -v`
Expected: FAIL with `AttributeError: 'ArgoCdClient' object has no attribute 'wait_for_sync'`

- [ ] **Step 10: Implement wait_for_sync**

```python
    def wait_for_sync(
        self,
        target_revision: str,
        *,
        timeout_s: float = 60,
        poll_interval_s: float = 2,
    ) -> None:
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            status = self._fetch_status()
            if status["revision"] == target_revision and status["status"] == "Synced":
                return
            time.sleep(poll_interval_s)
        raise ArgoCdSyncTimeoutError(
            f"app {self.app_name!r} did not sync to revision {target_revision!r} "
            f"within {timeout_s}s"
        )
```

- [ ] **Step 11: Run test to verify it passes**

Run: `uv run --all-packages pytest chaos/tests/test_argocd_sync.py::test_wait_for_sync_succeeds_after_polling -v`
Expected: PASS

- [ ] **Step 12: Write the failing test for wait_for_sync timing out**

```python
def test_wait_for_sync_raises_on_timeout(monkeypatch: "pytest.MonkeyPatch") -> None:
    monkeypatch.setattr("time.sleep", lambda _: None)
    transport = FakeArgoCdTransport()
    transport.set_synced_after("c" * 40, polls=1_000_000)  # never catches up
    client = _client(transport)

    with pytest.raises(ArgoCdSyncTimeoutError):
        client.wait_for_sync(target_revision="c" * 40, timeout_s=0.01, poll_interval_s=0)
```

Add `from chaos.argocd_sync import ArgoCdSyncTimeoutError` to imports.

- [ ] **Step 13: Run test to verify it fails, then verify it passes**

Run: `uv run --all-packages pytest chaos/tests/test_argocd_sync.py -v`
Expected: `test_wait_for_sync_raises_on_timeout` should already PASS given
Step 10's implementation (the deadline check handles it) — if it doesn't,
fix the loop condition until all 4 tests pass.

- [ ] **Step 14: Lint and typecheck**

Run: `uv run --all-packages ruff check chaos/src/chaos/argocd_sync.py chaos/tests/test_argocd_sync.py chaos/tests/fake_argocd.py && uv run --all-packages mypy chaos/src/chaos/argocd_sync.py chaos/tests/test_argocd_sync.py chaos/tests/fake_argocd.py`
Expected: no errors.

- [ ] **Step 15: Commit**

```bash
git add chaos/src/chaos/argocd_sync.py chaos/tests/test_argocd_sync.py chaos/tests/fake_argocd.py chaos/pyproject.toml uv.lock
git commit -m "feat(chaos): add Argo CD sync-status polling client"
```

## Task 3: Add the bad_deploy image-tag patch block to the kustomize overlay

**Files:**
- Modify: `deploy/boutique/overlay/kustomization.yaml`

**Interfaces:**
- Consumes: nothing from Tasks 1-2.
- Produces: a kustomize patch target that `bad_deploy.py` (Task 4) will
  rewrite in the Gitea-hosted clone of this same file. The patch must be
  a no-op (sets the image to its existing value) until `bad_deploy`
  rewrites it, so bringing up a fresh cluster never starts with the fault
  already injected.

Online Boutique's upstream manifests don't pin exact image tags for every
service identically, so this task adds one generic patch block that
`bad_deploy.py` will target by Deployment name (parameterized per
`--service`, matching today's behavior where `bad_deploy` requires
`--service`).

- [ ] **Step 1: Read the current image tag convention**

Run: `grep -A2 "image:" "deploy/boutique/base/kubernetes-manifests.yaml" | head -20`

Note the `repo:tag` format used (e.g. `us-central1-docker.pkg.dev/.../frontend:v0.10.3`
or similar — use whatever the real manifest shows).

- [ ] **Step 2: Add a placeholder comment documenting the patch chaos will manage**

Edit `deploy/boutique/overlay/kustomization.yaml`, add a comment block
right after the existing resource-trim comment (before the `patches:`
key's existing entries), documenting that `chaos bad_deploy` appends a
per-service image-tag patch to this same `patches` list at runtime — no
YAML content changes needed here, since the real patch is injected by
Task 4's code at runtime, not committed statically. If mypy/ruff/yaml
linting is not configured for this file, no test is needed for a
comment-only change.

```yaml
# chaos bad_deploy appends an image-tag override patch (targeting the
# Deployment named by --service) to this file's `patches` list at runtime,
# then commits it to this repo's Gitea mirror. revert() removes it again.
# See chaos/src/chaos/scenarios/bad_deploy.py.
```

- [ ] **Step 3: Verify the overlay still builds cleanly**

Run: `kubectl kustomize deploy/boutique/overlay/ > /dev/null`
Expected: no errors (comment-only change, should always succeed; this
confirms kustomize tooling is available and the file is still valid YAML).

- [ ] **Step 4: Commit**

```bash
git add deploy/boutique/overlay/kustomization.yaml
git commit -m "docs: note where chaos bad_deploy injects its image-tag patch"
```

## Task 4: Rewrite bad_deploy.py to use git_repo + argocd_sync

**Files:**
- Modify: `chaos/src/chaos/scenarios/bad_deploy.py`
- Modify: `chaos/tests/test_bad_deploy.py`
- Modify: `chaos/src/chaos/scenarios/base.py` (the `Scenario.inject`/
  `revert` signature currently takes `k8s: Any` — `bad_deploy` will
  instead take a `BoutiqueDeployRepo` + `ArgoCdClient` pair; confirm with
  `chaos/src/chaos/cli.py` how scenarios are constructed/dispatched before
  changing the signature, since other scenarios still use the k8s-based
  signature and must keep working unchanged)

**Interfaces:**
- Consumes: `chaos.git_repo.BoutiqueDeployRepo` (Task 1),
  `chaos.argocd_sync.ArgoCdClient` (Task 2).
- Produces: `BadDeployScenario.inject(self, repo: BoutiqueDeployRepo, argocd: ArgoCdClient, service: str) -> dict[str, Any]`
  and matching `revert(...)`. `ground_truth()` is unchanged.

- [ ] **Step 1: Read how the CLI dispatches scenario.inject/revert today**

Run: `grep -n "inject\|revert" chaos/src/chaos/cli.py`

Confirm whether the CLI passes one shared `k8s` argument to every
scenario's `inject`/`revert`, or constructs scenario-specific arguments.
If it's a single shared argument today, this task needs to special-case
`bad_deploy` in the CLI (an `if scenario.name == "bad_deploy":` branch
constructing `repo`/`argocd` instead of `k8s`) rather than changing the
shared `Scenario` ABC signature — do not change `base.py`'s abstract
method signature, since the other four scenarios (`crash_loop`, `oom`,
`cpu_throttle`, `slow_redis`) still use direct k8s API calls per the
spec's out-of-scope note. Keep `BadDeployScenario` as a `Scenario`
subclass but widen its own `inject`/`revert` parameter types beyond the
ABC's declared `k8s: Any` (the `Any` type already permits this without
a `# type: ignore`).

- [ ] **Step 2: Write the failing test for inject writing the patch, committing, pushing, and waiting for sync**

```python
# chaos/tests/test_bad_deploy.py — replace existing content
from pathlib import Path

import git
import httpx
import pytest
import yaml

from chaos.argocd_sync import ArgoCdClient
from chaos.git_repo import BoutiqueDeployRepo
from chaos.scenarios.bad_deploy import BadDeployScenario
from fake_argocd import FakeArgoCdTransport


@pytest.fixture
def seeded_remote(tmp_path: Path) -> Path:
    remote_path = tmp_path / "remote.git"
    git.Repo.init(remote_path, bare=True)
    seed_path = tmp_path / "seed"
    seed_repo = git.Repo.init(seed_path)
    overlay = {
        "resources": ["../base"],
        "patches": [
            {
                "target": {"kind": "Deployment", "name": "frontend"},
                "patch": (
                    "- op: replace\n"
                    "  path: /spec/template/spec/containers/0/image\n"
                    "  value: gcr.io/example/frontend:v1.0.0\n"
                ),
            }
        ],
    }
    (seed_path / "kustomization.yaml").write_text(yaml.dump(overlay))
    seed_repo.index.add(["kustomization.yaml"])
    seed_repo.index.commit("seed")
    seed_repo.create_remote("origin", str(remote_path))
    seed_repo.remote("origin").push(seed_repo.active_branch.name)
    return remote_path


def _repo_and_argocd(
    remote: Path, tmp_path: Path, transport: FakeArgoCdTransport
) -> tuple[BoutiqueDeployRepo, ArgoCdClient]:
    repo = BoutiqueDeployRepo(remote_url=str(remote), local_path=tmp_path / "wc")
    http_client = httpx.Client(transport=transport, base_url="http://argocd.local")
    argocd = ArgoCdClient(
        base_url="http://argocd.local",
        app_name="boutique",
        token="fake",
        http_client=http_client,
    )
    return repo, argocd


def test_inject_commits_bad_tag_pushes_and_waits_for_sync(
    seeded_remote: Path, tmp_path: Path
) -> None:
    transport = FakeArgoCdTransport()
    repo, argocd = _repo_and_argocd(seeded_remote, tmp_path, transport)
    repo.ensure_cloned()
    transport.set_synced_after("PLACEHOLDER", polls=2)
    scenario = BadDeployScenario()

    snapshot = scenario.inject(repo, argocd, "frontend")

    assert snapshot == {"image": "gcr.io/example/frontend:v1.0.0"}
    overlay = yaml.safe_load((repo.local_path / "kustomization.yaml").read_text())
    patched_image = overlay["patches"][0]["patch"]
    assert "does-not-exist" in patched_image
    # inject() must have waited for the real commit SHA, not the placeholder.
    assert transport.synced_revision == repo.head_sha()


def test_revert_restores_prior_image_and_waits_for_sync(
    seeded_remote: Path, tmp_path: Path
) -> None:
    transport = FakeArgoCdTransport()
    repo, argocd = _repo_and_argocd(seeded_remote, tmp_path, transport)
    repo.ensure_cloned()
    transport.set_synced_after("PLACEHOLDER", polls=1)
    scenario = BadDeployScenario()
    snapshot = scenario.inject(repo, argocd, "frontend")
    transport.set_synced_after("PLACEHOLDER", polls=1)

    scenario.revert(repo, argocd, "frontend", snapshot)

    overlay = yaml.safe_load((repo.local_path / "kustomization.yaml").read_text())
    patched_image = overlay["patches"][0]["patch"]
    assert "gcr.io/example/frontend:v1.0.0" in patched_image
    assert "does-not-exist" not in patched_image
    assert transport.synced_revision == repo.head_sha()


def test_ground_truth_uses_passed_service() -> None:
    gt = BadDeployScenario().ground_truth("frontend")
    assert gt["affected_service"] == "frontend"
    assert "image tag" in gt["root_cause_label"]
```

Note: `set_synced_after`'s `revision` argument is a placeholder string
here because the real commit SHA isn't known until `inject()` computes
it internally — the fake only needs `synced_after_polls` to force a few
iterations; `inject()`/`revert()`'s own code must set
`argocd.wait_for_sync(target_revision=<the real pushed SHA>, ...)`, and
the fake transport's `handle_request` always reports whatever
`pending_revision` was last set — fix the fake in Step 2 of Task 2 if this
mismatch surfaces test flakiness (it shouldn't, since the fake ignores
the requested revision and just serves whatever's been configured).

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run --all-packages pytest chaos/tests/test_bad_deploy.py -v`
Expected: FAIL — `BadDeployScenario.inject()` doesn't accept `(repo, argocd, service)` yet.

- [ ] **Step 4: Implement the rewritten BadDeployScenario**

```python
# chaos/src/chaos/scenarios/bad_deploy.py
from typing import Any, ClassVar

import yaml

from chaos.argocd_sync import ArgoCdClient
from chaos.git_repo import BoutiqueDeployRepo
from chaos.scenarios.base import Scenario, load_definition

_OVERLAY_FILE = "kustomization.yaml"
_IMAGE_PATCH_PATH = "/spec/template/spec/containers/0/image"


class BadDeployScenario(Scenario):
    name: ClassVar[str] = "bad_deploy"
    requires_service: ClassVar[bool] = True

    def inject(
        self, repo: BoutiqueDeployRepo, argocd: ArgoCdClient, service: str
    ) -> dict[str, Any]:
        definition = load_definition(self.name)
        bad_tag = definition.default_params["bad_tag"]

        overlay = self._load_overlay(repo)
        patch_entry = self._find_or_create_patch(overlay, service)
        prior_image = self._current_image(patch_entry)
        repo_name = prior_image.rsplit(":", 1)[0]
        new_image = f"{repo_name}:{bad_tag}"
        self._set_image(patch_entry, new_image)
        self._save_overlay(repo, overlay)

        sha = repo.commit_and_push(f"chaos: inject bad_deploy on {service}")
        argocd.wait_for_sync(target_revision=sha)

        return {"image": prior_image}

    def revert(
        self,
        repo: BoutiqueDeployRepo,
        argocd: ArgoCdClient,
        service: str,
        saved_state: dict[str, Any],
    ) -> None:
        overlay = self._load_overlay(repo)
        patch_entry = self._find_or_create_patch(overlay, service)
        self._set_image(patch_entry, saved_state["image"])
        self._save_overlay(repo, overlay)

        sha = repo.commit_and_push(f"chaos: revert bad_deploy on {service}")
        argocd.wait_for_sync(target_revision=sha)

    def _load_overlay(self, repo: BoutiqueDeployRepo) -> dict[str, Any]:
        path = repo.local_path / _OVERLAY_FILE
        data: dict[str, Any] = yaml.safe_load(path.read_text())
        return data

    def _save_overlay(self, repo: BoutiqueDeployRepo, overlay: dict[str, Any]) -> None:
        repo.write_file(_OVERLAY_FILE, yaml.dump(overlay))

    def _find_or_create_patch(
        self, overlay: dict[str, Any], service: str
    ) -> dict[str, Any]:
        patches: list[dict[str, Any]] = overlay.setdefault("patches", [])
        for entry in patches:
            if entry["target"].get("name") == service and _IMAGE_PATCH_PATH in entry["patch"]:
                return entry
        raise ValueError(
            f"no image-tag patch found for service {service!r} in overlay — "
            "Task 3 must seed a no-op patch for every service bad_deploy can target"
        )

    def _current_image(self, patch_entry: dict[str, Any]) -> str:
        patch_ops = yaml.safe_load(patch_entry["patch"])
        for op in patch_ops:
            if op["path"] == _IMAGE_PATCH_PATH:
                image: str = op["value"]
                return image
        raise ValueError("patch entry has no image replace op")

    def _set_image(self, patch_entry: dict[str, Any], image: str) -> None:
        patch_ops = yaml.safe_load(patch_entry["patch"])
        for op in patch_ops:
            if op["path"] == _IMAGE_PATCH_PATH:
                op["value"] = image
        patch_entry["patch"] = yaml.dump(patch_ops)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run --all-packages pytest chaos/tests/test_bad_deploy.py -v`
Expected: all 3 tests PASS. If `test_inject_commits_bad_tag_pushes_and_waits_for_sync`
fails on the overlay's patch lookup, re-check that Task 3's seeded fixture
patch (in the test, not the real overlay file) matches the
`_find_or_create_patch` matching logic exactly (`target.name == service`
and the image-replace path present in `patch`).

- [ ] **Step 6: Update the CLI dispatch for bad_deploy (if base.py's shared signature can't be reused)**

Based on what Step 1 of this task found: if the CLI calls
`scenario.inject(k8s, service)` uniformly, add a branch in
`chaos/src/chaos/cli.py`'s inject/revert commands:

Add two factory functions following the same naming convention as the
existing `_build_k8s_client`:

```python
def _build_boutique_deploy_repo() -> BoutiqueDeployRepo:
    repo = BoutiqueDeployRepo(
        remote_url=settings.gitea_repo_url,
        local_path=settings.chaos_state_dir / "boutique-deploy",
    )
    repo.ensure_cloned()
    return repo


def _build_argocd_client() -> ArgoCdClient:
    return ArgoCdClient(
        base_url=settings.argocd_url, app_name="boutique", token=settings.argocd_token
    )
```

(Match whatever config/settings pattern `chaos/src/chaos/cli.py` already
uses for other values like namespace or kubeconfig — read the file
first and follow its existing convention for where `settings` comes from
rather than introducing a new one.) Then, in the existing `inject`/
`revert` commands, after the existing "already active" / "no active
injection" guard checks (do not move the branch before them):

```python
if scenario.name == "bad_deploy":
    repo = _build_boutique_deploy_repo()
    argocd = _build_argocd_client()
    snapshot = scenario.inject(repo, argocd, service)
else:
    snapshot = scenario.inject(k8s, service)
```

Add the equivalent branch for `revert`, calling
`scenario.revert(repo, argocd, active.service, active.saved_state)` in
the `bad_deploy` case.

- [ ] **Step 7: Write a CLI-level test confirming the single-active-scenario guard still applies to bad_deploy through the new dispatch branch**

`chaos/tests/test_cli.py` already tests this invariant for
`crash_loop`/`oom` using `_patched(tmp_path, fake)` (patches
`chaos.cli._state_path` and `chaos.cli._build_k8s_client`). The
`bad_deploy` branch added in Step 6 constructs a `BoutiqueDeployRepo` and
`ArgoCdClient` instead of calling `_build_k8s_client` — patch whatever
Step 6's branch actually calls to build those (e.g.
`chaos.cli._build_boutique_deploy_repo` /
`chaos.cli._build_argocd_client`, matching the factory-function naming
`_build_k8s_client` already establishes) so these tests never touch a
real git remote or Argo CD server. Add to `chaos/tests/test_cli.py`:

```python
def test_inject_bad_deploy_refuses_when_another_scenario_active(tmp_path: Path) -> None:
    fake = FakeK8sClient()
    _seed_paymentservice(fake)
    p1, p2 = _patched(tmp_path, fake)
    with (
        p1,
        p2,
        patch("chaos.cli._build_boutique_deploy_repo"),
        patch("chaos.cli._build_argocd_client"),
    ):
        runner.invoke(app, ["inject", "crash_loop"])
        result = runner.invoke(app, ["inject", "bad_deploy", "--service", "frontend"])

    assert result.exit_code != 0
    assert "already active" in result.stdout.lower()


def test_revert_errors_when_nothing_active_for_bad_deploy(tmp_path: Path) -> None:
    fake = FakeK8sClient()
    p1, p2 = _patched(tmp_path, fake)
    with (
        p1,
        p2,
        patch("chaos.cli._build_boutique_deploy_repo"),
        patch("chaos.cli._build_argocd_client"),
    ):
        result = runner.invoke(app, ["revert", "bad_deploy"])
    assert result.exit_code != 0
    assert "no active injection" in result.stdout.lower()
```

Both tests must pass without the patched `_build_boutique_deploy_repo`/
`_build_argocd_client` mocks ever being called — if they are called, the
guard in `inject()`/`revert()` (the existing "already active" / "no
active injection" checks) ran too late, after the bad_deploy branch
already started constructing real clients.

- [ ] **Step 8: Run test to verify it fails, then implement/fix until it passes**

Run: `uv run --all-packages pytest chaos/tests/test_cli.py -k bad_deploy -v`
Expected: initially FAIL if the new dispatch branch skips the guard check
(it shouldn't, since the guard runs in `inject()`/`revert()` before the
`if scenario.name == "bad_deploy":` branch per Task 4 Step 6 — if it
fails, the branch was inserted in the wrong place; move it after the
existing guard checks). Then PASS.

- [ ] **Step 9: Run the full chaos test suite**

Run: `uv run --all-packages pytest chaos/tests/ -v`
Expected: all tests PASS, including the other 4 scenarios' tests
(`test_crash_loop.py`, `test_oom.py`, `test_cpu_throttle.py`,
`test_slow_redis.py`), confirming they're unaffected.

- [ ] **Step 10: Lint and typecheck**

Run: `uv run --all-packages ruff check chaos/ && uv run --all-packages mypy chaos/`
Expected: no errors.

- [ ] **Step 11: Commit**

```bash
git add chaos/src/chaos/scenarios/bad_deploy.py chaos/tests/test_bad_deploy.py chaos/tests/test_cli.py chaos/src/chaos/cli.py
git commit -m "feat(chaos): rewrite bad_deploy to inject/revert via Git commit + Argo CD sync"
```

## Task 5: Gitea + Argo CD cluster setup in Makefile

**Files:**
- Create: `deploy/k8s/gitea-values.yaml`
- Create: `deploy/k8s/argocd-boutique-app.yaml`
- Modify: `Makefile`

**Interfaces:**
- Consumes: nothing from code — this is cluster bring-up wiring only.
- Produces: a running Gitea instance with a `boutique-deploy` repo seeded
  from `deploy/boutique/`, and an Argo CD `Application` syncing it into
  the `boutique` namespace. This is the runtime counterpart Task 4's
  `BoutiqueDeployRepo`/`ArgoCdClient` callers point at via
  `settings.gitea_repo_url`/`settings.argocd_url` (Task 4, Step 6).

This task has no unit tests — it's cluster bring-up shell/YAML, verified
by running `make up` against a real kind cluster, which is out of scope
for an automated test suite (no kind/podman available in this
environment). Document the manual verification steps instead.

- [ ] **Step 1: Write Gitea Helm values**

```yaml
# deploy/k8s/gitea-values.yaml
gitea:
  admin:
    username: chaos-admin
    password: chaos-admin-password
    email: chaos-admin@example.local
  config:
    server:
      OFFLINE_MODE: true
    service:
      DISABLE_REGISTRATION: true
persistence:
  enabled: false
postgresql:
  enabled: false
postgresql-ha:
  enabled: false
valkey-cluster:
  enabled: false
```

(Gitea's Helm chart needs an embedded DB; using its default bundled
SQLite via `GITEA__database__DB_TYPE` if the chart supports it keeps this
single-node and dependency-free — check the chart's actual default
values with `helm show values gitea-charts/gitea` once the repo is added
in Step 2, and adjust this file if SQLite isn't the chart default.)

- [ ] **Step 2: Add Gitea + Argo CD Helm repos and install steps to the Makefile**

Edit `Makefile`'s `up` target: after the existing `bitnami` repo add/update
block and before the `kafka`/`postgres` installs, add:

```makefile
	helm repo add gitea-charts https://dl.gitea.io/charts/ >/dev/null 2>&1 || true
	helm repo add argo https://argoproj.github.io/argo-helm >/dev/null 2>&1 || true
	helm repo update gitea-charts argo
	kubectl create namespace gitops --dry-run=client -o yaml | kubectl apply -f -
	helm upgrade --install gitea gitea-charts/gitea \
		--namespace gitops \
		-f deploy/k8s/gitea-values.yaml \
		--wait --timeout 5m
	helm upgrade --install argocd argo/argo-cd \
		--namespace gitops \
		--wait --timeout 5m
```

- [ ] **Step 3: Replace the direct kubectl apply -k step with the one-time Gitea push + Argo CD Application apply**

Edit `Makefile`'s `up` target: remove line 17
(`kubectl apply -k deploy/boutique/overlay/`) and the line 18
`kubectl wait --for=condition=Available deployment --all -n boutique --timeout=300s`
(Argo CD's own sync will create the namespace/deployments; the wait is
replaced by waiting on Argo CD's Application health below). Replace with,
right after the Gitea/Argo CD installs from Step 2:

`deploy/boutique/` is a subdirectory of this repo, not its own git repo,
so the seed step copies its contents into a scratch directory and
initializes a fresh single-commit history there before pushing to Gitea
— it does not try to `git clone` the subdirectory path.

```makefile
	@if ! kubectl exec -n gitops deploy/gitea -- gitea admin repo list 2>/dev/null | grep -q boutique-deploy; then \
		kubectl port-forward -n gitops svc/gitea-http 3001:3000 >/tmp/triage-gitea-forward.log 2>&1 & \
			GITEA_PID=$$!; \
			for i in $$(seq 1 30); do nc -z localhost 3001 && break; sleep 1; done; \
			curl -s -u chaos-admin:chaos-admin-password -X POST \
				http://localhost:3001/api/v1/user/repos \
				-H "Content-Type: application/json" \
				-d '{"name":"boutique-deploy","private":false}' >/dev/null; \
			rm -rf /tmp/boutique-deploy-seed; \
			mkdir -p /tmp/boutique-deploy-seed && cp -r deploy/boutique/. /tmp/boutique-deploy-seed/ && \
			cd /tmp/boutique-deploy-seed && git init -q -b main && git add -A && git commit -q -m "seed" && \
			git remote add origin http://chaos-admin:chaos-admin-password@localhost:3001/chaos-admin/boutique-deploy.git && \
			git push -u origin main; \
			kill $$GITEA_PID; \
	fi
	kubectl apply -f deploy/k8s/argocd-boutique-app.yaml
	kubectl wait --for=jsonpath='{.status.health.status}'=Healthy \
		application/boutique -n gitops --timeout=300s
```

- [ ] **Step 4: Write the Argo CD Application manifest**

```yaml
# deploy/k8s/argocd-boutique-app.yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: boutique
  namespace: gitops
spec:
  project: default
  source:
    repoURL: http://gitea-http.gitops.svc.cluster.local:3000/chaos-admin/boutique-deploy.git
    targetRevision: main
    path: overlay
  destination:
    server: https://kubernetes.default.svc
    namespace: boutique
  syncPolicy:
    automated:
      prune: true
      selfHeal: true
    syncOptions:
      - CreateNamespace=true
```

- [ ] **Step 5: Update the echo block at the end of `up` to mention Gitea/Argo CD**

Edit the `@echo` lines at the end of the `up` target, add:

```makefile
	@echo "Gitea:      http://localhost:3001  (run: kubectl port-forward -n gitops svc/gitea-http 3001:3000, login chaos-admin/chaos-admin-password)"
	@echo "Argo CD:    kubectl port-forward -n gitops svc/argocd-server 8081:443 (login: admin / $$(kubectl -n gitops get secret argocd-initial-admin-secret -o jsonpath='{.data.password}' | base64 -d))"
```

- [ ] **Step 6: Document manual verification in chaos/README.md**

Add a short note to `chaos/README.md`'s existing scenario table area,
e.g. right after the `bad_deploy` table row context, noting that
`bad_deploy` now requires `make up` to have provisioned Gitea + Argo CD
(it will fail with a clear connection error otherwise) — this sets
expectations for anyone running `chaos inject bad_deploy` without having
run `make up` first.

```markdown
Note: `bad_deploy` requires Gitea and Argo CD to be running (provisioned
by `make up`) — it injects/reverts its fault via a Git commit that Argo
CD syncs, not a direct Kubernetes API call like the other scenarios.
```

- [ ] **Step 7: Commit**

```bash
git add deploy/k8s/gitea-values.yaml deploy/k8s/argocd-boutique-app.yaml Makefile chaos/README.md
git commit -m "feat: provision Gitea + Argo CD in make up, sync Online Boutique via GitOps"
```

## Task 6: End-to-end manual verification (not automated)

**Files:** none — verification only.

- [ ] **Step 1: Bring up a fresh cluster**

Run: `make down; make up`
Expected: completes without error; Gitea and Argo CD come up; the
`boutique` Application reaches `Healthy`/`Synced`; `kubectl get pods -n boutique`
shows all Online Boutique pods Running.

- [ ] **Step 2: Inject bad_deploy and confirm it's visible via Argo CD history**

Run: `uv run --all-packages chaos inject bad_deploy --service frontend`
Expected: command succeeds; `kubectl get pods -n boutique -l app=frontend`
shows `ImagePullBackOff` within the wait window; Argo CD's UI/CLI
(`kubectl port-forward -n gitops svc/argocd-server 8081:443`, browse to
`https://localhost:8081`) shows a new sync revision for the `boutique`
Application matching the commit chaos just pushed.

- [ ] **Step 3: Revert and confirm recovery**

Run: `uv run --all-packages chaos revert`
Expected: command succeeds; frontend pods return to Running within the
wait window; Argo CD shows another new synced revision.

- [ ] **Step 4: Report results to the user**

Summarize pass/fail of Steps 1-3 before considering this plan complete —
do not mark this plan done on unit tests alone, since Tasks 5-6 have no
automated coverage by design (cluster bring-up).
