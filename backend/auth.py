import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Literal
from urllib.parse import urlparse

import jwt

if __package__:
    from .errors import AuthenticationRequiredError
else:
    from errors import AuthenticationRequiredError


AuthMode = Literal["disabled", "oidc", "hs256"]
KNOWN_ROLES = frozenset({"designer", "reviewer", "admin"})
OIDC_ALLOWED_ALGORITHMS = frozenset(
    {"RS256", "RS384", "RS512", "ES256", "ES384", "ES512", "EdDSA"},
)


@dataclass(frozen=True)
class AuthSettings:
    environment: str
    mode: AuthMode
    issuer: str = ""
    audience: str = ""
    jwks_url: str = ""
    algorithms: tuple[str, ...] = ("RS256",)
    roles_claim: str = "roles"
    name_claim: str = "name"
    clock_skew_seconds: int = 30
    hs256_secret: str = field(default="", repr=False)

    def __post_init__(self) -> None:
        if self.environment == "production" and self.mode != "oidc":
            raise ValueError("AUTH_MODE=oidc is required when APP_ENV=production")
        if self.mode == "oidc":
            if not self.issuer or not self.audience or not self.jwks_url:
                raise ValueError(
                    "AUTH_ISSUER, AUTH_AUDIENCE and AUTH_JWKS_URL are required "
                    "when AUTH_MODE=oidc",
                )
            parsed_jwks_url = urlparse(self.jwks_url)
            if parsed_jwks_url.scheme != "https":
                raise ValueError("AUTH_JWKS_URL must use HTTPS")
            if not self.algorithms or not set(self.algorithms).issubset(
                OIDC_ALLOWED_ALGORITHMS,
            ):
                raise ValueError("OIDC algorithms must be explicitly asymmetric")
        if self.mode == "hs256":
            if self.algorithms != ("HS256",):
                raise ValueError("AUTH_ALGORITHMS must be HS256 in hs256 mode")
            if len(self.hs256_secret.encode("utf-8")) < 32:
                raise ValueError("AUTH_HS256_SECRET must contain at least 32 bytes")
        if self.clock_skew_seconds < 0 or self.clock_skew_seconds > 300:
            raise ValueError("AUTH_CLOCK_SKEW_SECONDS must be between 0 and 300")

    @classmethod
    def from_env(
        cls,
        environ: Mapping[str, str] | None = None,
    ) -> "AuthSettings":
        values = environ if environ is not None else os.environ
        raw_mode = values.get("AUTH_MODE", "disabled").strip().lower()
        if raw_mode not in {"disabled", "oidc", "hs256"}:
            raise ValueError("AUTH_MODE must be disabled, oidc or hs256")
        default_algorithms = "HS256" if raw_mode == "hs256" else "RS256"
        raw_algorithms = values.get("AUTH_ALGORITHMS", default_algorithms)
        algorithms = tuple(
            algorithm.strip()
            for algorithm in raw_algorithms.split(",")
            if algorithm.strip()
        )
        try:
            clock_skew_seconds = int(
                values.get("AUTH_CLOCK_SKEW_SECONDS", "30").strip(),
            )
        except ValueError as exc:
            raise ValueError("AUTH_CLOCK_SKEW_SECONDS must be an integer") from exc
        return cls(
            environment=values.get("APP_ENV", "production").strip().lower(),
            mode=raw_mode,
            issuer=values.get("AUTH_ISSUER", "").strip(),
            audience=values.get("AUTH_AUDIENCE", "").strip(),
            jwks_url=values.get("AUTH_JWKS_URL", "").strip(),
            algorithms=algorithms,
            roles_claim=values.get("AUTH_ROLES_CLAIM", "roles").strip() or "roles",
            name_claim=values.get("AUTH_NAME_CLAIM", "name").strip() or "name",
            clock_skew_seconds=clock_skew_seconds,
            hs256_secret=values.get("AUTH_HS256_SECRET", ""),
        )


@dataclass(frozen=True)
class AuthPrincipal:
    subject: str
    display_name: str
    roles: frozenset[str]
    authenticated: bool

    def has_any_role(self, allowed_roles: set[str] | frozenset[str]) -> bool:
        return bool(self.roles.intersection(allowed_roles))


class TokenVerifier:
    def __init__(self, settings: AuthSettings) -> None:
        self.settings = settings
        self._jwks_client = (
            jwt.PyJWKClient(
                settings.jwks_url,
                cache_jwk_set=True,
                lifespan=300,
                timeout=5,
            )
            if settings.mode == "oidc"
            else None
        )

    def verify(self, token: str | None) -> AuthPrincipal:
        if self.settings.mode == "disabled":
            return AuthPrincipal(
                subject="local-development",
                display_name="Local Development",
                roles=KNOWN_ROLES,
                authenticated=False,
            )
        if not token:
            raise AuthenticationRequiredError()
        try:
            key = self._verification_key(token)
            claims = jwt.decode(
                token,
                key=key,
                algorithms=list(self.settings.algorithms),
                audience=self.settings.audience,
                issuer=self.settings.issuer,
                leeway=self.settings.clock_skew_seconds,
                options={"require": ["exp", "iat", "iss", "aud", "sub"]},
            )
        except jwt.PyJWTError as exc:
            raise AuthenticationRequiredError() from exc
        subject = claims.get("sub")
        if not isinstance(subject, str) or not subject.strip():
            raise AuthenticationRequiredError()
        display_name = claims.get(self.settings.name_claim)
        if not isinstance(display_name, str) or not display_name.strip():
            display_name = subject
        roles = self._extract_roles(claims)
        return AuthPrincipal(
            subject=subject,
            display_name=display_name,
            roles=roles,
            authenticated=True,
        )

    def _verification_key(self, token: str):
        if self.settings.mode == "hs256":
            return self.settings.hs256_secret
        assert self._jwks_client is not None
        return self._jwks_client.get_signing_key_from_jwt(token).key

    def _extract_roles(self, claims: dict[str, Any]) -> frozenset[str]:
        value: Any = claims.get(self.settings.roles_claim)
        if value is None:
            value = claims
            for part in self.settings.roles_claim.split("."):
                if not isinstance(value, dict):
                    value = None
                    break
                value = value.get(part)
        if isinstance(value, str):
            candidates = value.replace(",", " ").split()
        elif isinstance(value, list):
            candidates = [role for role in value if isinstance(role, str)]
        else:
            candidates = []
        return frozenset(role for role in candidates if role in KNOWN_ROLES)
