from porter.core.models import PrivacyClass, RequestContext
from porter.policy import PolicyEngine
from tests.fakes import make_request


def request(privacy_class: PrivacyClass, allow_cloud: bool = False) -> RequestContext:
    return make_request(
        privacy_class=privacy_class,
        allow_cloud=allow_cloud,
    )


def test_local_only_blocks_cloud() -> None:
    decision = PolicyEngine().evaluate(request(PrivacyClass.LOCAL_ONLY))
    assert decision.local_allowed is True
    assert decision.cloud_allowed is False


def test_cloud_requires_explicit_permission() -> None:
    decision = PolicyEngine().evaluate(request(PrivacyClass.CLOUD_ALLOWED))
    assert decision.cloud_allowed is False


def test_explicit_cloud_permission_is_allowed() -> None:
    decision = PolicyEngine().evaluate(
        request(PrivacyClass.CLOUD_ALLOWED, allow_cloud=True)
    )
    assert decision.cloud_allowed is True


def test_redacted_cloud_fails_closed_until_redaction_exists() -> None:
    decision = PolicyEngine().evaluate(
        request(PrivacyClass.CLOUD_ALLOWED_REDACTED, allow_cloud=True)
    )
    assert decision.cloud_allowed is False
    assert decision.redaction_required is True
