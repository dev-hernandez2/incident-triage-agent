"""Integration test: the triage-agent ServiceAccount must not be able to mutate
cluster state. Requires a live cluster (`make up`) with kubectl configured
against kind-triage; skipped otherwise.
"""

import shutil
import subprocess

import pytest


def _kind_cluster_reachable() -> bool:
    if shutil.which("kubectl") is None:
        return False
    result = subprocess.run(
        ["kubectl", "get", "namespace", "triage"],
        capture_output=True,
        timeout=10,
    )
    return result.returncode == 0


pytestmark = pytest.mark.skipif(
    not _kind_cluster_reachable(), reason="no live kind-triage cluster available"
)


def test_service_account_cannot_delete_pods() -> None:
    result = subprocess.run(
        [
            "kubectl",
            "auth",
            "can-i",
            "delete",
            "pods",
            "--as=system:serviceaccount:triage:triage-agent",
            "-n",
            "boutique",
        ],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.stdout.strip() == "no"


def test_service_account_can_list_pods() -> None:
    result = subprocess.run(
        [
            "kubectl",
            "auth",
            "can-i",
            "list",
            "pods",
            "--as=system:serviceaccount:triage:triage-agent",
            "-n",
            "boutique",
        ],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.stdout.strip() == "yes"


def test_service_account_cannot_get_secrets() -> None:
    result = subprocess.run(
        [
            "kubectl",
            "auth",
            "can-i",
            "get",
            "secrets",
            "--as=system:serviceaccount:triage:triage-agent",
            "-n",
            "boutique",
        ],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.stdout.strip() == "no"
