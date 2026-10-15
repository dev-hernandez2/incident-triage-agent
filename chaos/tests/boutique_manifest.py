from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

_REPO_ROOT = Path(__file__).resolve().parents[2]
_MANIFEST_PATH = _REPO_ROOT / "deploy" / "boutique" / "base" / "kubernetes-manifests.yaml"


@lru_cache(maxsize=1)
def _deployments() -> dict[str, dict[str, Any]]:
    docs = yaml.safe_load_all(_MANIFEST_PATH.read_text())
    return {
        doc["metadata"]["name"]: doc
        for doc in docs
        if doc and doc.get("kind") == "Deployment"
    }


def real_containers(deployment_name: str) -> list[dict[str, Any]]:
    """The real container list for a deployment, straight from the manifest
    this repo deploys — so scenario tests exercise real container names
    (e.g. 'server', not 'cartservice') and the full field set (ports,
    probes, securityContext) rather than a hand-written fiction."""
    deployment = _deployments()[deployment_name]
    containers = deployment["spec"]["template"]["spec"]["containers"]
    return list(containers)
