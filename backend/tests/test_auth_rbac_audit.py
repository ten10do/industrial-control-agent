import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import jwt
import pytest
from fastapi.testclient import TestClient

from backend.auth import AuthSettings, TokenVerifier
from backend.errors import AuthenticationRequiredError
from backend.llm_client import FakeLLMClient
from backend.main import app, get_llm_client, get_token_verifier
from backend.plan_repository import PlanRepository


SECRET = "test-auth-secret-that-is-longer-than-thirty-two-bytes"
ISSUER = "https://identity.example.com/"
AUDIENCE = "industrial-control-agent"
GENERATE_PAYLOAD = {
    "control_object": "Motor",
    "input_devices": "Start, stop, emergency stop and overload inputs",
    "output_devices": "Motor contactor and alarm",
    "control_requirements": "Start and stop the motor with emergency protection.",
    "model_provider": "DeepSeek",
}


def auth_settings(**overrides) -> AuthSettings:
    values = {
        "environment": "test",
        "mode": "hs256",
        "issuer": ISSUER,
        "audience": AUDIENCE,
        "algorithms": ("HS256",),
        "hs256_secret": SECRET,
    }
    values.update(overrides)
    return AuthSettings(**values)


def token_for(
    subject: str,
    roles: list[str],
    *,
    name: str | None = None,
    issuer: str = ISSUER,
    audience: str = AUDIENCE,
    secret: str = SECRET,
    expires_delta: timedelta = timedelta(minutes=10),
) -> str:
    now = datetime.now(timezone.utc)
    return jwt.encode(
        {
            "sub": subject,
            "name": name or subject,
            "roles": roles,
            "iss": issuer,
            "aud": audience,
            "iat": now,
            "exp": now + expires_delta,
        },
        secret,
        algorithm="HS256",
    )


def authorization(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def client() -> TestClient:
    verifier = TokenVerifier(auth_settings())
    app.dependency_overrides[get_llm_client] = lambda: FakeLLMClient()
    app.dependency_overrides[get_token_verifier] = lambda: verifier
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def test_production_environment_requires_oidc() -> None:
    with pytest.raises(ValueError, match="AUTH_MODE=oidc"):
        AuthSettings(environment="production", mode="disabled")
    with pytest.raises(ValueError, match="AUTH_MODE=oidc"):
        AuthSettings.from_env({})


def test_oidc_configuration_rejects_symmetric_algorithms_and_insecure_jwks() -> None:
    with pytest.raises(ValueError, match="HTTPS"):
        AuthSettings(
            environment="production",
            mode="oidc",
            issuer=ISSUER,
            audience=AUDIENCE,
            jwks_url="http://identity.example.com/jwks",
        )
    with pytest.raises(ValueError, match="asymmetric"):
        AuthSettings(
            environment="production",
            mode="oidc",
            issuer=ISSUER,
            audience=AUDIENCE,
            jwks_url="https://identity.example.com/jwks",
            algorithms=("HS256",),
        )


@pytest.mark.parametrize(
    "token",
    [
        token_for("designer-1", ["designer"], secret="different-secret-of-adequate-length-123"),
        token_for("designer-1", ["designer"], issuer="https://attacker.example.com/"),
        token_for("designer-1", ["designer"], audience="another-api"),
        token_for("designer-1", ["designer"], expires_delta=timedelta(minutes=-5)),
    ],
)
def test_verifier_rejects_invalid_signature_and_registered_claims(token: str) -> None:
    verifier = TokenVerifier(auth_settings(clock_skew_seconds=0))

    with pytest.raises(AuthenticationRequiredError):
        verifier.verify(token)


def test_verifier_supports_nested_role_claims() -> None:
    now = datetime.now(timezone.utc)
    token = jwt.encode(
        {
            "sub": "keycloak-user",
            "name": "Keycloak User",
            "realm_access": {"roles": ["designer", "untrusted-role"]},
            "iss": ISSUER,
            "aud": AUDIENCE,
            "iat": now,
            "exp": now + timedelta(minutes=10),
        },
        SECRET,
        algorithm="HS256",
    )
    verifier = TokenVerifier(auth_settings(roles_claim="realm_access.roles"))

    principal = verifier.verify(token)

    assert principal.roles == frozenset({"designer"})


def test_protected_routes_require_identity_and_role(client: TestClient) -> None:
    missing = client.post("/generate", json=GENERATE_PAYLOAD)
    reviewer_only = client.post(
        "/generate",
        headers=authorization(token_for("reviewer-1", ["reviewer"])),
        json=GENERATE_PAYLOAD,
    )
    designer = client.post(
        "/generate",
        headers=authorization(token_for("designer-1", ["designer"], name="Designer One")),
        json=GENERATE_PAYLOAD,
    )

    assert missing.status_code == 401
    assert missing.json()["code"] == "AUTHENTICATION_REQUIRED"
    assert reviewer_only.status_code == 403
    assert reviewer_only.json()["code"] == "AUTHORIZATION_DENIED"
    assert designer.status_code == 200
    persisted = client.get(
        f"/plans/{designer.json()['plan_id']}",
        headers=authorization(token_for("designer-1", ["designer"])),
    )
    assert persisted.json()["created_by"] == "designer-1"
    assert persisted.json()["created_by_name"] == "Designer One"


def test_designers_cannot_access_another_designers_plan(client: TestClient) -> None:
    created = client.post(
        "/generate",
        headers=authorization(token_for("designer-1", ["designer"])),
        json=GENERATE_PAYLOAD,
    ).json()

    denied = client.get(
        f"/plans/{created['plan_id']}",
        headers=authorization(token_for("designer-2", ["designer"])),
    )
    reviewer_allowed = client.get(
        f"/plans/{created['plan_id']}",
        headers=authorization(token_for("reviewer-1", ["reviewer"])),
    )

    assert denied.status_code == 403
    assert reviewer_allowed.status_code == 200


def test_plan_inbox_is_filtered_by_role(client: TestClient) -> None:
    designer_one = token_for("inbox-designer-1", ["designer"])
    designer_two = token_for("inbox-designer-2", ["designer"])
    first = client.post(
        "/generate",
        headers=authorization(designer_one),
        json=GENERATE_PAYLOAD,
    ).json()
    second = client.post(
        "/generate",
        headers=authorization(designer_two),
        json=GENERATE_PAYLOAD,
    ).json()

    own_inbox = client.get("/plans", headers=authorization(designer_one)).json()["plans"]
    reviewer_inbox = client.get(
        "/plans",
        headers=authorization(token_for("inbox-reviewer", ["reviewer"])),
    ).json()["plans"]

    assert first["plan_id"] in {plan["plan_id"] for plan in own_inbox}
    assert second["plan_id"] not in {plan["plan_id"] for plan in own_inbox}
    assert {first["plan_id"], second["plan_id"]}.issubset(
        {plan["plan_id"] for plan in reviewer_inbox},
    )


def test_creator_cannot_self_review_even_with_reviewer_role(client: TestClient) -> None:
    creator_token = token_for(
        "dual-role-user",
        ["designer", "reviewer"],
        name="Dual Role User",
    )
    created = client.post(
        "/generate",
        headers=authorization(creator_token),
        json=GENERATE_PAYLOAD,
    ).json()

    response = client.post(
        f"/plans/{created['plan_id']}/reviews",
        headers=authorization(creator_token),
        json={"decision": "approved", "comment": "Self approval"},
    )

    assert response.status_code == 403
    assert response.json()["code"] == "SELF_REVIEW_DENIED"


def test_reviewer_identity_is_derived_from_token_and_audit_chain_is_complete(
    client: TestClient,
) -> None:
    designer_token = token_for("designer-1", ["designer"], name="Designer One")
    reviewer_token = token_for("reviewer-1", ["reviewer"], name="Reviewer One")
    admin_token = token_for("admin-1", ["admin"], name="Audit Admin")
    created = client.post(
        "/generate",
        headers=authorization(designer_token),
        json=GENERATE_PAYLOAD,
    ).json()
    plan_id = created["plan_id"]

    forged_identity = client.post(
        f"/plans/{plan_id}/reviews",
        headers=authorization(reviewer_token),
        json={
            "decision": "approved",
            "reviewer": "Forged Reviewer",
            "comment": "Should be rejected",
        },
    )
    assert forged_identity.status_code == 422

    approved = client.post(
        f"/plans/{plan_id}/reviews",
        headers=authorization(reviewer_token),
        json={"decision": "approved", "comment": "Independent check complete"},
    )
    assert approved.status_code == 200
    assert approved.json()["reviewer_sub"] == "reviewer-1"
    assert approved.json()["reviewer"] == "Reviewer One"

    exported = client.get(
        f"/plans/{plan_id}/export",
        headers=authorization(designer_token),
    )
    assert exported.status_code == 200

    plan_audit = client.get(
        f"/plans/{plan_id}/audit",
        headers=authorization(designer_token),
    )
    global_audit = client.get(
        "/audit/events",
        headers=authorization(admin_token),
    )
    denied_global_audit = client.get(
        "/audit/events",
        headers=authorization(reviewer_token),
    )

    assert plan_audit.status_code == 200
    assert plan_audit.json()["chain_valid"] is True
    actions = {event["action"] for event in plan_audit.json()["events"]}
    assert {
        "plan.created",
        "plan.review.approved",
        "plan.exported",
    }.issubset(actions)
    assert global_audit.status_code == 200
    assert global_audit.json()["chain_valid"] is True
    assert denied_global_audit.status_code == 403


def test_audit_table_rejects_update_and_delete(tmp_path: Path) -> None:
    repository = PlanRepository(tmp_path / "audit.db")
    repository.initialize()
    repository.create_plan(
        source="generate",
        report_markdown="# Plan",
        response={"report_markdown": "# Plan"},
        review_required=False,
        actor_sub="designer-1",
        actor_name="Designer One",
        request_id="request-1",
    )

    with sqlite3.connect(repository.database_path) as connection:
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            connection.execute(
                "UPDATE audit_events SET actor_name = 'Tampered'",
            )
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            connection.execute("DELETE FROM audit_events")

    assert repository.verify_audit_chain() is True
