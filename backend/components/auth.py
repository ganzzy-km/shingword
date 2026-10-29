"""Authentication building blocks; not registered on the legacy user API.

Google code flow follows https://developers.google.com/identity/openid-connect/openid-connect.
Database User/ownership mapping and approved session lifetime are prerequisites
for production integration. No first-login admin or implicit user adoption.
"""
from dataclasses import dataclass, field
import base64
import hashlib
import hmac
import math
import secrets
import time
import logging
from urllib.parse import urlencode, urlsplit

from google.oauth2.id_token import verify_oauth2_token
from google.auth.transport.requests import Request
from itsdangerous import URLSafeTimedSerializer, BadSignature


class AuthDenied(ValueError):
    pass


@dataclass(frozen=True)
class Principal:
    id: str
    sub: str
    role: str
    status: str
    session_version: int
    email: str = ""
    email_verified: bool = False


def require_active(user):
    if not isinstance(user, Principal) or user.status != "ACTIVE" or user.role not in {"USER", "ADMIN"}:
        raise AuthDenied("ACCESS_DENIED")


def require_private_owner(user, owner_id, *, expires_at=None, now=None):
    require_active(user)
    if not owner_id or owner_id != user.id:
        raise AuthDenied("RESOURCE_UNAVAILABLE")
    if expires_at is not None:
        if (type(now) not in (int, float) or type(expires_at) not in (int, float)
                or not math.isfinite(now) or not math.isfinite(expires_at) or now >= expires_at):
            raise AuthDenied("RESOURCE_UNAVAILABLE")


def require_public_permission(user, action):
    require_active(user)
    if action == "ADD" and user.email_verified is True and user.email == "ps00000@onedu.jje.go.kr":
        return
    if action == "DELETE" and user.role == "ADMIN":
        return
    raise AuthDenied("ACCESS_DENIED")


def validate_google_claims(claims, *, client_id, nonce, now):
    # Called only AFTER cryptographic verification by google-auth.
    if not isinstance(claims, dict) or not client_id or not nonce:
        raise AuthDenied("TOKEN_INVALID")
    aud = claims.get("aud")
    audiences = aud if isinstance(aud, list) else [aud]
    exp, iat = claims.get("exp"), claims.get("iat")
    nbf = claims.get("nbf", iat)
    if (claims.get("iss") not in {"accounts.google.com", "https://accounts.google.com"}
            or client_id not in audiences or (len(audiences) > 1 and claims.get("azp") != client_id)
            or claims.get("azp", client_id) != client_id
            or type(exp) not in (int, float) or type(iat) not in (int, float)
            or type(nbf) not in (int, float) or not math.isfinite(nbf) or nbf > now
            or not math.isfinite(exp) or not math.isfinite(iat) or not iat <= now < exp
            or not isinstance(claims.get("sub"), str) or not claims["sub"]
            or not isinstance(claims.get("nonce"), str)
            or not hmac.compare_digest(claims["nonce"].encode(), nonce.encode())):
        raise AuthDenied("TOKEN_INVALID")
    return {"sub": claims["sub"], "issuer": "https://accounts.google.com",
            "email": claims.get("email", ""), "emailVerified": claims.get("email_verified") is True,
            **public_google_profile(claims),
            "initialRole": "USER", "initialStatus": "PENDING_APPROVAL"}


def public_google_profile(claims):
    """Bounded, optional display metadata from cryptographically verified claims."""
    name = claims.get('name', claims.get('displayName'))
    picture = claims.get('picture', claims.get('pictureUrl'))
    result = {}
    if isinstance(name, str) and 0 < len(name.strip()) <= 120:
        result['displayName'] = name.strip()
    if isinstance(picture, str) and len(picture) <= 512:
        try:
            parsed = urlsplit(picture)
            if parsed.scheme == 'https' and parsed.hostname == 'lh3.googleusercontent.com' and not parsed.username and not parsed.password and not parsed.fragment and parsed.port in (None, 443):
                result['pictureUrl'] = picture
        except ValueError:
            pass  # Optional display metadata must not break a valid login.
    return result


@dataclass
class Challenge:
    state: str = field(repr=False)
    nonce: str = field(repr=False)
    verifier: str = field(repr=False)
    created: float
    consumed: bool = False


class GoogleCodeFlow:
    def __init__(self, *, client_id, client_secret, redirect_uri, state_ttl,
                 external_approved=False, testing=False, exchange=None, certificate_request=None):
        try:
            parsed = urlsplit(redirect_uri)
            _ = parsed.port
        except (ValueError, TypeError):
            raise AuthDenied("OIDC_CONFIGURATION_REQUIRED") from None
        if (not client_id or not client_secret or parsed.scheme != "https" or not parsed.hostname
                or parsed.fragment or parsed.query or parsed.username or parsed.password
                or any(c.isspace() or ord(c) < 32 for c in redirect_uri)
                or type(state_ttl) is not int or state_ttl < 1):
            raise AuthDenied("OIDC_CONFIGURATION_REQUIRED")
        if not testing and (exchange is not None or certificate_request is not None):
            raise AuthDenied("TEST_PROVIDER_FORBIDDEN")
        self.client_id, self._client_secret, self.redirect_uri = client_id, client_secret, redirect_uri
        self.state_ttl, self.external_approved, self.testing = state_ttl, external_approved, testing
        self._exchange, self._certificate_request = exchange, certificate_request

    def begin(self, *, now):
        if not self.external_approved and not self.testing:
            raise AuthDenied("PENDING_EXTERNAL")
        challenge = Challenge(secrets.token_urlsafe(32), secrets.token_urlsafe(32), secrets.token_urlsafe(48), now)
        pkce = base64.urlsafe_b64encode(hashlib.sha256(challenge.verifier.encode()).digest()).rstrip(b"=").decode()
        url = "https://accounts.google.com/o/oauth2/v2/auth?" + urlencode({
            "client_id": self.client_id, "redirect_uri": self.redirect_uri, "response_type": "code",
            "scope": "openid email profile", "state": challenge.state, "nonce": challenge.nonce,
            "code_challenge": pkce, "code_challenge_method": "S256"})
        return url, challenge  # Challenge belongs in a server-side login session.

    def finish(self, challenge, *, state, code, now):
        if (not self.external_approved and not self.testing) or challenge.consumed:
            raise AuthDenied("LOGIN_UNAVAILABLE")
        if not isinstance(state, str) or not code or not hmac.compare_digest(challenge.state, state) or not 0 <= now - challenge.created < self.state_ttl:
            raise AuthDenied("STATE_INVALID")
        challenge.consumed = True
        stage = 'TOKEN_EXCHANGE'
        try:
            payload = {"code": code, "client_id": self.client_id, "client_secret": self._client_secret,
                       "redirect_uri": self.redirect_uri, "grant_type": "authorization_code", "code_verifier": challenge.verifier}
            if self.testing:
                if self._exchange is None or self._certificate_request is None:
                    raise AuthDenied("TEST_PROVIDER_REQUIRED")
                tokens = self._exchange(payload)
                request = self._certificate_request
            else:
                import requests
                response = requests.post("https://oauth2.googleapis.com/token", data=payload, timeout=10, allow_redirects=False)
                response.raise_for_status()
                tokens, request = response.json(), Request()
            stage = 'SIGNATURE_AND_STANDARD_CLAIMS'
            claims = verify_oauth2_token(tokens["id_token"], request, audience=self.client_id)
            stage = 'CLAIMS_POLICY'
            # Google issues the ID token during exchange, after callback arrival.
            # Use the current verification time; retain the injected test clock.
            verified_at = now if self.testing else time.time()
            return validate_google_claims(claims, client_id=self.client_id, nonce=challenge.nonce, now=verified_at)
        except Exception as error:
            # Never surface tokens, provider responses or secret-bearing request exceptions.
            detail = 'UNCLASSIFIED'
            if stage == 'TOKEN_EXCHANGE' and not self.testing:
                import requests
                if isinstance(error, requests.HTTPError):
                    status = getattr(error.response, 'status_code', None)
                    detail = 'HTTP_' + str(status) if status in {400,401,403,429,500,502,503} else 'HTTP_REJECTED'
                    try:
                        provider_code = error.response.json().get('error')
                        if provider_code in {'invalid_client','invalid_grant','invalid_request','unauthorized_client','unsupported_grant_type'}:
                            detail += '_' + provider_code.upper()
                    except Exception:
                        pass
                elif isinstance(error, requests.exceptions.SSLError):detail = 'TLS_VALIDATION_FAILED'
                elif isinstance(error, requests.exceptions.Timeout):detail = 'NETWORK_TIMEOUT'
                elif isinstance(error, requests.exceptions.ConnectionError):detail = 'NETWORK_CONNECTION_FAILED'
            logging.getLogger(__name__).warning('OIDC verification failed at %s (%s)', stage, detail)
            raise AuthDenied("TOKEN_INVALID") from None


class SessionBoundary:
    cookie_attributes = {"httponly": True, "secure": True, "samesite": "Lax", "path": "/"}

    def __init__(self, secret, *, max_age):
        if not isinstance(secret, str) or len(secret) < 32 or not isinstance(max_age, int) or max_age < 1:
            raise AuthDenied("SESSION_CONFIGURATION_REQUIRED")
        self.serializer = URLSafeTimedSerializer(secret, salt="geulbit-session-v1")
        self.max_age = max_age

    def issue(self, user, *, profile=None):
        require_active(user)
        csrf = secrets.token_urlsafe(32)
        return self.serializer.dumps({"uid": user.id, "sv": user.session_version, "csrf": csrf, "profile": public_google_profile(profile or {})}), csrf

    def verify(self, cookie, *, load_user, csrf=None, mutating=False):
        try:
            value = self.serializer.loads(cookie, max_age=self.max_age)
            user = load_user(value["uid"])
            require_active(user)
            if user.id != value["uid"] or type(value["sv"]) is not int or user.session_version != value["sv"]:
                raise AuthDenied("SESSION_INVALID")
            if mutating and (not isinstance(csrf, str) or not hmac.compare_digest(csrf, value["csrf"])):
                raise AuthDenied("CSRF_INVALID")
            return user
        except (BadSignature, KeyError, TypeError, AuthDenied):
            raise AuthDenied("ACCESS_DENIED") from None
