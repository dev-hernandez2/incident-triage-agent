from pathlib import Path

import git
import httpx
import pytest
import yaml
from boutique_manifest import real_containers
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


@pytest.fixture
def unseeded_remote(tmp_path: Path) -> Path:
    """An overlay with no existing image-tag patch for any service, matching
    the real cold-start state of deploy/boutique/overlay/kustomization.yaml
    (Task 3 only seeded a documentation comment, no image-tag patch entries)."""
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
                    "  path: /spec/template/spec/containers/0/resources\n"
                    "  value:\n"
                    "    requests: {cpu: 50m, memory: 64Mi}\n"
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


class _AutoSyncRepo(BoutiqueDeployRepo):
    """A BoutiqueDeployRepo whose commit_and_push also tells the fake Argo CD
    transport which revision to report as synced, N polls later.

    The real fake transport (chaos/tests/fake_argocd.py) has no visibility
    into git at all -- it only answers whatever HTTP GETs ArgoCdClient sends
    it, and a /sync-status GET carries no revision. So it cannot "learn" the
    real commit SHA that inject()/revert() compute internally and later pass
    to argocd.wait_for_sync(target_revision=sha). Pre-seeding the fake with a
    placeholder string (as a prior draft of this test did) can never satisfy
    wait_for_sync's exact-match check against the real SHA, which made
    wait_for_sync poll until its 60s default timeout on every run.
    This subclass closes that gap in the test harness only: it captures the
    real SHA the moment commit_and_push produces it and immediately arms the
    fake transport with it, matching the pattern chaos/tests/test_argocd_sync.py
    already uses (configuring the fake with the exact revision wait_for_sync
    will request, never a placeholder)."""

    def __init__(
        self, remote_url: str, local_path: Path, transport: FakeArgoCdTransport, polls: int
    ) -> None:
        super().__init__(remote_url=remote_url, local_path=local_path)
        self._transport = transport
        self._polls = polls

    def commit_and_push(self, message: str) -> str:
        sha = super().commit_and_push(message)
        self._transport.set_synced_after(sha, polls=self._polls)
        return sha


def _repo_and_argocd(
    remote: Path, tmp_path: Path, transport: FakeArgoCdTransport, polls: int = 2
) -> tuple[BoutiqueDeployRepo, ArgoCdClient]:
    repo = _AutoSyncRepo(
        remote_url=str(remote), local_path=tmp_path / "wc", transport=transport, polls=polls
    )
    http_client = httpx.Client(transport=transport, base_url="http://argocd.local")
    argocd = ArgoCdClient(
        base_url="http://argocd.local",
        app_name="boutique",
        token="fake",
        http_client=http_client,
    )
    return repo, argocd


def test_inject_commits_bad_tag_pushes_and_waits_for_sync(
    seeded_remote: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("time.sleep", lambda _: None)
    transport = FakeArgoCdTransport()
    repo, argocd = _repo_and_argocd(seeded_remote, tmp_path, transport, polls=2)
    repo.ensure_cloned()
    scenario = BadDeployScenario()

    snapshot = scenario.inject(repo, argocd, "frontend")

    assert snapshot == {"image": "gcr.io/example/frontend:v1.0.0", "created": False}
    overlay = yaml.safe_load((repo.local_path / "kustomization.yaml").read_text())
    patched_image = overlay["patches"][0]["patch"]
    assert "does-not-exist" in patched_image
    # inject() must have waited for the real commit SHA, not a placeholder.
    assert transport.synced_revision == repo.head_sha()


def test_revert_restores_prior_image_and_waits_for_sync(
    seeded_remote: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("time.sleep", lambda _: None)
    transport = FakeArgoCdTransport()
    repo, argocd = _repo_and_argocd(seeded_remote, tmp_path, transport, polls=1)
    repo.ensure_cloned()
    scenario = BadDeployScenario()
    snapshot = scenario.inject(repo, argocd, "frontend")

    scenario.revert(repo, argocd, "frontend", snapshot)

    overlay = yaml.safe_load((repo.local_path / "kustomization.yaml").read_text())
    patched_image = overlay["patches"][0]["patch"]
    assert "gcr.io/example/frontend:v1.0.0" in patched_image
    assert "does-not-exist" not in patched_image
    assert transport.synced_revision == repo.head_sha()


def test_inject_creates_patch_entry_when_none_exists_for_service(
    unseeded_remote: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Cold-start case: deploy/boutique/overlay/kustomization.yaml has no
    image-tag patch entry for `frontend` yet (only the pre-existing resource
    patch from Task 3's real overlay shape). inject() must create one rather
    than raising, using frontend's current image tag from the base manifest
    as the snapshot value."""
    monkeypatch.setattr("time.sleep", lambda _: None)
    transport = FakeArgoCdTransport()
    repo, argocd = _repo_and_argocd(unseeded_remote, tmp_path, transport, polls=1)
    repo.ensure_cloned()
    scenario = BadDeployScenario()
    real_image = real_containers("frontend")[0]["image"]

    snapshot = scenario.inject(repo, argocd, "frontend")

    assert snapshot == {"image": real_image, "created": True}
    overlay = yaml.safe_load((repo.local_path / "kustomization.yaml").read_text())
    image_patches = [
        entry
        for entry in overlay["patches"]
        if entry["target"].get("name") == "frontend"
        and "/spec/template/spec/containers/0/image" in entry["patch"]
    ]
    assert len(image_patches) == 1
    bad_tag = real_image.rsplit(":", 1)[0] + ":does-not-exist"
    assert bad_tag in image_patches[0]["patch"]
    # the pre-existing resource patch for frontend must be left untouched
    resource_patches = [
        entry
        for entry in overlay["patches"]
        if entry["target"].get("name") == "frontend"
        and "/spec/template/spec/containers/0/resources" in entry["patch"]
    ]
    assert len(resource_patches) == 1
    assert transport.synced_revision == repo.head_sha()


def test_revert_deletes_patch_entry_it_created(
    unseeded_remote: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When inject() creates a brand-new image-tag patch entry for a service
    (the cold-start case — no pre-existing patch), revert() must delete that
    entry entirely rather than merely resetting its image value, restoring
    the overlay's `patches` list to its exact pre-inject shape."""
    monkeypatch.setattr("time.sleep", lambda _: None)
    transport = FakeArgoCdTransport()
    repo, argocd = _repo_and_argocd(unseeded_remote, tmp_path, transport, polls=1)
    repo.ensure_cloned()
    scenario = BadDeployScenario()
    before_overlay = yaml.safe_load((repo.local_path / "kustomization.yaml").read_text())
    before_patches = before_overlay["patches"]

    snapshot = scenario.inject(repo, argocd, "frontend")
    assert snapshot["created"] is True

    scenario.revert(repo, argocd, "frontend", snapshot)

    after_overlay = yaml.safe_load((repo.local_path / "kustomization.yaml").read_text())
    after_patches = after_overlay["patches"]
    assert after_patches == before_patches
    image_patches = [
        entry
        for entry in after_patches
        if entry["target"].get("name") == "frontend"
        and "/spec/template/spec/containers/0/image" in entry["patch"]
    ]
    assert len(image_patches) == 0


def test_revert_resets_but_does_not_delete_preexisting_patch_entry(
    seeded_remote: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When an image-tag patch entry already existed before inject() ran
    (seeded_remote's scenario), revert() must reset its image value in place
    and must NOT delete the entry — it didn't create it, so it must not
    destroy it."""
    monkeypatch.setattr("time.sleep", lambda _: None)
    transport = FakeArgoCdTransport()
    repo, argocd = _repo_and_argocd(seeded_remote, tmp_path, transport, polls=1)
    repo.ensure_cloned()
    scenario = BadDeployScenario()

    snapshot = scenario.inject(repo, argocd, "frontend")
    assert snapshot["created"] is False

    scenario.revert(repo, argocd, "frontend", snapshot)

    overlay = yaml.safe_load((repo.local_path / "kustomization.yaml").read_text())
    image_patches = [
        entry
        for entry in overlay["patches"]
        if entry["target"].get("name") == "frontend"
        and "/spec/template/spec/containers/0/image" in entry["patch"]
    ]
    assert len(image_patches) == 1
    assert "gcr.io/example/frontend:v1.0.0" in image_patches[0]["patch"]
    assert "does-not-exist" not in image_patches[0]["patch"]


_COMMENTED_OVERLAY = """\
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization

# Trim container resource requests/limits so the whole stack fits comfortably
# under ~8GB RAM. See the real overlay file for full rationale.

# chaos bad_deploy appends an image-tag override patch (targeting the
# Deployment named by --service) to this file's `patches` list at runtime,
# then commits it to this repo's Gitea mirror. revert() removes it again.
resources:
  - ../base
patches:
  - target:
      kind: Deployment
      name: frontend
    patch: |-
      - op: replace
        path: /spec/template/spec/containers/0/resources
        value:
          requests: {cpu: 50m, memory: 64Mi}
"""


def test_save_overlay_preserves_comments_on_noop_roundtrip(tmp_path: Path) -> None:
    """_load_overlay()/_save_overlay() round-trip the real overlay file's
    comments and formatting (via ruamel.yaml in round-trip mode), since this
    file is committed to a Gitea-hosted GitOps repo Argo CD reconciles and
    silently stripping its documentation on every chaos run is a real
    operational regression, not cosmetic."""

    class _FakeRepo:
        def __init__(self, local_path: Path) -> None:
            self.local_path = local_path

        def write_file(self, relative_path: str, content: str) -> None:
            (self.local_path / relative_path).write_text(content)

    (tmp_path / "kustomization.yaml").write_text(_COMMENTED_OVERLAY)
    fake_repo = _FakeRepo(tmp_path)
    scenario = BadDeployScenario()

    overlay = scenario._load_overlay(fake_repo)  # type: ignore[arg-type]
    scenario._save_overlay(fake_repo, overlay)  # type: ignore[arg-type]

    result = (tmp_path / "kustomization.yaml").read_text()
    assert "# chaos bad_deploy appends an image-tag override patch" in result
    assert "revert() removes it again" in result
    assert "Trim container resource requests/limits" in result


def test_ground_truth_uses_passed_service() -> None:
    gt = BadDeployScenario().ground_truth("frontend")
    assert gt["affected_service"] == "frontend"
    assert "image tag" in gt["root_cause_label"]
