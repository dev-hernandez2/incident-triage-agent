from chaos.scenarios.expired_tls_cert import ExpiredTlsCertScenario
from fake_k8s import FakeK8sClient

_VALID_CERT = "-----BEGIN CERTIFICATE-----\nVALIDPLACEHOLDER\n-----END CERTIFICATE-----"


def test_inject_replaces_cert_with_expired_one_and_returns_prior_secret() -> None:
    fake = FakeK8sClient()
    fake.seed_secret("frontend-tls", {"tls.crt": _VALID_CERT, "tls.key": "validkey"})
    scenario = ExpiredTlsCertScenario()

    snapshot = scenario.inject(fake, "frontend")

    assert snapshot == {"tls.crt": _VALID_CERT, "tls.key": "validkey"}
    patched = fake.get_secret("frontend-tls")
    assert "EXPIREDTESTCERTIFICATE" in patched["tls.crt"]
    assert patched["tls.key"] == "validkey"


def test_revert_restores_prior_secret() -> None:
    fake = FakeK8sClient()
    fake.seed_secret("frontend-tls", {"tls.crt": _VALID_CERT, "tls.key": "validkey"})
    scenario = ExpiredTlsCertScenario()
    snapshot = scenario.inject(fake, "frontend")

    scenario.revert(fake, "frontend", snapshot)

    assert fake.get_secret("frontend-tls") == {"tls.crt": _VALID_CERT, "tls.key": "validkey"}


def test_ground_truth_uses_fixed_service() -> None:
    gt = ExpiredTlsCertScenario().ground_truth("frontend")
    assert gt["affected_service"] == "frontend"
    assert "expired" in gt["root_cause_label"].lower()
