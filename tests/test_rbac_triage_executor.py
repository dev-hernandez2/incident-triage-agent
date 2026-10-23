"""Integration test: the triage-executor ServiceAccount may patch
deployments in boutique but nothing else. Requires a live cluster
(`make up`) with kubectl configured against kind-triage; skipped
otherwise.
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


def test_service_account_can_patch_deployments_in_boutique() -> None:
    result = subprocess.run(
        [
            "kubectl",
            "auth",
            "can-i",
            "patch",
            "deployments",
            "--as=system:serviceaccount:triage:triage-executor",
            "-n",
            "boutique",
        ],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.stdout.strip() == "yes"


def test_service_account_cannot_delete_deployments() -> None:
    result = subprocess.run(
        [
            "kubectl",
            "auth",
            "can-i",
            "delete",
            "deployments",
            "--as=system:serviceaccount:triage:triage-executor",
            "-n",
            "boutique",
        ],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.stdout.strip() == "no"


def test_service_account_cannot_patch_deployments_outside_boutique() -> None:
    result = subprocess.run(
        [
            "kubectl",
            "auth",
            "can-i",
            "patch",
            "deployments",
            "--as=system:serviceaccount:triage:triage-executor",
            "-n",
            "triage",
        ],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.stdout.strip() == "no"


def test_service_account_cannot_get_secrets() -> None:
    result = subprocess.run(
        [
            "kubectl",
            "auth",
            "can-i",
            "get",
            "secrets",
            "--as=system:serviceaccount:triage:triage-executor",
            "-n",
            "boutique",
        ],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.stdout.strip() == "no"
