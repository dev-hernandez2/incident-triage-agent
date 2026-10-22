from functools import lru_cache
from pathlib import Path
from typing import Any, ClassVar

import yaml

from chaos.argocd_sync import ArgoCdClient
from chaos.git_repo import BoutiqueDeployRepo
from chaos.scenarios.base import Scenario, load_definition

_OVERLAY_FILE = "kustomization.yaml"
_IMAGE_PATCH_PATH = "/spec/template/spec/containers/0/image"
_REPO_ROOT = Path(__file__).resolve().parents[4]
_BASE_MANIFEST_PATH = _REPO_ROOT / "deploy" / "boutique" / "base" / "kubernetes-manifests.yaml"


@lru_cache(maxsize=1)
def _base_deployments() -> dict[str, dict[str, Any]]:
    docs = yaml.safe_load_all(_BASE_MANIFEST_PATH.read_text())
    return {
        doc["metadata"]["name"]: doc for doc in docs if doc and doc.get("kind") == "Deployment"
    }


def _current_base_image(service: str) -> str:
    """The service's current image tag as checked into the base manifest —
    used as the snapshot/patch value the first time bad_deploy targets a
    service, before any image-tag patch entry exists for it in the overlay."""
    deployment = _base_deployments()[service]
    containers = deployment["spec"]["template"]["spec"]["containers"]
    image: str = containers[0]["image"]
    return image


class BadDeployScenario(Scenario):
    name: ClassVar[str] = "bad_deploy"
    requires_service: ClassVar[bool] = True

    def inject(  # type: ignore[override]
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

    def revert(  # type: ignore[override]
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

    def _find_or_create_patch(self, overlay: dict[str, Any], service: str) -> dict[str, Any]:
        patches: list[dict[str, Any]] = overlay.setdefault("patches", [])
        for entry in patches:
            if entry["target"].get("name") == service and _IMAGE_PATCH_PATH in entry["patch"]:
                return entry

        # No image-tag patch entry exists yet for this service (the real
        # cold-start state of deploy/boutique/overlay/kustomization.yaml,
        # which Task 3 deliberately left unseeded). Create one, using the
        # service's current image tag from the base manifest so the first
        # inject() snapshots the real pre-fault image rather than fabricating
        # one.
        current_image = _current_base_image(service)
        patch_text = yaml.dump(
            [{"op": "replace", "path": _IMAGE_PATCH_PATH, "value": current_image}]
        )
        new_entry: dict[str, Any] = {
            "target": {"kind": "Deployment", "name": service},
            "patch": patch_text,
        }
        patches.append(new_entry)
        return new_entry

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
